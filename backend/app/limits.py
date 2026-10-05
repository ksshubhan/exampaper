"""Generation limits.

A slot is **reserved** before any work happens and **refunded** if that work
then fails, so a crashed generation never costs a user their free paper.

The reservation is a single `UPDATE … RETURNING`. One statement means one row
lock: ten simultaneous requests from the same free user queue behind each other,
and Postgres re-evaluates the `WHERE` against the freshly committed row as each
one acquires the lock — so exactly one wins. Read-then-write would let all ten
read `total_generations = 0` and all ten succeed.

The plan is read *inside* that statement rather than from the ORM object, so a
subscription that changed between authentication and reservation is honoured
without a retry loop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth import get_current_user
from .config import get_settings
from .db import get_db
from .models import PLAN_MONTHLY, User

#: The daily cap is a calendar day here, not a rolling 24 hours, and not UTC —
#: a parent in London who generates at 23:50 gets a fresh allowance at midnight
#: their time, including through BST.
LONDON = ZoneInfo("Europe/London")

UPGRADE_REQUIRED_DETAIL = {"code": "upgrade_required"}
DAILY_LIMIT_REACHED_DETAIL = {"code": "daily_limit_reached"}

#: Where the live reservation is parked on `request.state`, so a request that
#: dies before the route body runs can still give the slot back. See the
#: RequestValidationError handler in `main`.
STATE_ATTR = "generation_reservation"


def london_today() -> date:
    """Today's Europe/London calendar date. The single clock seam; tests patch it."""
    return datetime.now(tz=LONDON).date()


# `day_generations` only counts today: any row whose `day_date` is not today is
# treated as zero and rebased, which is the daily reset — no cron job needed.
_RESERVE_SQL = text(
    """
    UPDATE users SET
        total_generations = total_generations + 1,
        day_generations =
            CASE WHEN day_date = :today THEN day_generations + 1 ELSE 1 END,
        day_date = :today
    WHERE id = :user_id
      AND CASE
            WHEN plan = :monthly_plan THEN
                (CASE WHEN day_date = :today THEN day_generations ELSE 0 END)
                    < :daily_limit
            ELSE total_generations < :free_limit
          END
    RETURNING plan, total_generations, day_generations
    """
)

# Clamped at zero, and the day counter moves only if the row is still on the day
# the slot was taken from — a refund that straddles midnight must not borrow
# from tomorrow's allowance.
_REFUND_SQL = text(
    """
    UPDATE users SET
        total_generations =
            CASE WHEN total_generations > 0 THEN total_generations - 1 ELSE 0 END,
        day_generations = CASE
            WHEN day_date = :day AND day_generations > 0 THEN day_generations - 1
            ELSE day_generations
        END
    WHERE id = :user_id
    """
)


@dataclass
class Reservation:
    """A consumed generation slot.

    Held by the route handler so that it, and not this module, decides what
    counts as a failed generation worth refunding.

    The user is carried as a bare id, not as the ORM row: a refund can happen
    from an exception handler, by which point the request's session has closed
    and that row is detached.
    """

    db: Session
    user_id: uuid.UUID
    #: The Europe/London day the slot was taken from.
    day: date
    plan: str
    total_generations: int
    day_generations: int
    _refunded: bool = field(default=False, repr=False)

    def refund(self) -> None:
        """Give the slot back. Safe to call more than once."""
        if self._refunded:
            return
        self._refunded = True
        self.db.execute(_REFUND_SQL, {"user_id": self.user_id, "day": self.day})
        self.db.commit()

    @property
    def refunded(self) -> bool:
        return self._refunded


def current_plan(db: Session, user_id: uuid.UUID, fallback: str) -> str:
    """The plan as the database has it right now, for choosing the error code."""
    plan = db.execute(
        text("SELECT plan FROM users WHERE id = :user_id"), {"user_id": user_id}
    ).scalar_one_or_none()
    return plan or fallback


def over_limit(plan: str) -> HTTPException:
    """The refusal that fits the plan: upgrade for free, wait for monthly."""
    if plan == PLAN_MONTHLY:
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=DAILY_LIMIT_REACHED_DETAIL,
        )
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=UPGRADE_REQUIRED_DETAIL,
    )


def pending_reservation(request: Request) -> Reservation | None:
    """The slot this request took, if it got that far."""
    return getattr(request.state, STATE_ATTR, None)


def reserve_generation(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Reservation:
    """FastAPI dependency: take one generation slot, or refuse the request.

    Reusable as-is — `POST /api/generate-worksheet` adopts it in one line when
    it is written, and a worksheet then costs the same as a paper.
    """
    settings = get_settings()
    today = london_today()
    user_id = user.id
    row = db.execute(
        _RESERVE_SQL,
        {
            "today": today,
            "user_id": user_id,
            "monthly_plan": PLAN_MONTHLY,
            "daily_limit": settings.daily_generation_limit,
            "free_limit": settings.free_generation_limit,
        },
    ).one_or_none()

    if row is None:
        # Nothing was written, but the SELECT that found the user opened a
        # transaction; close it before reading the plan back.
        db.rollback()
        raise over_limit(current_plan(db, user_id, user.plan))

    db.commit()
    # The counters on the ORM row are stale now; send a later read of them back
    # to the database rather than serving the pre-reservation numbers.
    db.expire(user)
    reservation = Reservation(
        db=db,
        user_id=user_id,
        day=today,
        plan=row.plan,
        total_generations=row.total_generations,
        day_generations=row.day_generations,
    )
    setattr(request.state, STATE_ATTR, reservation)
    return reservation
