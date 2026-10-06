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

Two counters, counting different things:

* `day_generations` / `total_generations` — papers *delivered*. Refundable, so
  a parent who closes the tab keeps their free paper.
* `day_attempts` — generations *started*, on every plan. Spent when a slot is
  reserved and never given back. Because the refund hands the reserved slot
  straight back, a script could otherwise loop generate → disconnect →
  generate for unbounded compute at no cost; the attempt cap is what bounds
  that. It counts work, so only a request that reserved a slot — and therefore
  went on to do work — spends one: a refusal (402, 429) starts no generation
  and costs nothing, which also means a free user who has run out cannot be
  locked out of the day they upgrade.
* `day_renders` — PDFs *rendered*, on every plan. Rendering reserves no
  generation slot, because re-downloading a paper you already own has to stay
  free; that leaves one headless Chromium per call with nothing bounding it at
  all. This counter is that bound, and it is separate from the other two so a
  day of legitimate re-downloading cannot eat into the allowance for making
  papers. It buys a *browser launch*, so a render that fails or times out
  keeps it — the launch happened. The one refundable case is a request turned
  away at the concurrency gate, which never launched anything; that refund is
  safe to offer because `hold_render_slot` allows an account only one
  in-flight render, so nobody can mine it in a loop.
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
TOO_MANY_ATTEMPTS_DETAIL = {"code": "too_many_attempts"}
TOO_MANY_RENDERS_DETAIL = {"code": "too_many_renders"}

#: Where the live reservation is parked on `request.state`, so a request that
#: dies before the route body runs can still give the slot back. See the
#: RequestValidationError handler in `main`.
STATE_ATTR = "generation_reservation"


def london_today() -> date:
    """Today's Europe/London calendar date. The single clock seam; tests patch it."""
    return datetime.now(tz=LONDON).date()


# `day_generations` only counts today: any row whose `day_date` is not today is
# treated as zero and rebased, which is the daily reset — no cron job needed.
# `day_attempts` resets the same way, off its own `attempt_date`.

#: The plan's own allowance, evaluated against the row as it stands.
_SLOT_AVAILABLE = """
    CASE
        WHEN before.plan = :monthly_plan THEN before.day_count < :daily_limit
        ELSE before.total_generations < :free_limit
    END
"""

# The `before` CTE is what makes two decisions out of one statement. `FOR
# UPDATE` takes the lock and — in READ COMMITTED, after waiting on a concurrent
# writer — re-reads the freshly committed row, so the flags below are computed
# from current values. They have to come from the CTE rather than from
# `RETURNING`: `RETURNING` sees the *updated* row, where `total_generations`
# has already been incremented and `< :free_limit` would read false for the
# very request that just succeeded.
#
# Every counter here, attempts included, moves only when a slot is actually
# reserved — so a refused request leaves the row exactly as it found it and the
# caller rolls back. A reservation is what precedes real work, and real work is
# what the cap is for.
_RESERVE_SQL = text(
    f"""
    WITH before AS (
        SELECT
            id,
            plan,
            total_generations,
            CASE WHEN day_date = :today THEN day_generations ELSE 0 END
                AS day_count,
            CASE WHEN attempt_date = :today THEN day_attempts ELSE 0 END
                AS attempt_count
        FROM users
        WHERE id = :user_id
        FOR UPDATE
    )
    UPDATE users SET
        day_attempts = CASE
            WHEN {_SLOT_AVAILABLE} THEN before.attempt_count + 1
            ELSE users.day_attempts
        END,
        attempt_date = CASE
            WHEN {_SLOT_AVAILABLE} THEN :today
            ELSE users.attempt_date
        END,
        total_generations = users.total_generations
            + CASE WHEN {_SLOT_AVAILABLE} THEN 1 ELSE 0 END,
        day_generations = CASE
            WHEN {_SLOT_AVAILABLE} THEN before.day_count + 1
            ELSE users.day_generations
        END,
        day_date = CASE
            WHEN {_SLOT_AVAILABLE} THEN :today
            ELSE users.day_date
        END
    FROM before
    WHERE users.id = before.id
      AND before.attempt_count < :max_attempts
    RETURNING
        users.plan,
        users.total_generations,
        users.day_generations,
        users.day_attempts,
        ({_SLOT_AVAILABLE}) AS reserved
    """
)

# Renders are given back only when none was started — see `RenderCount.refund`.
# Clamped and day-guarded like the generation refund below, and for the same
# reason: a refund that straddles midnight must not borrow from tomorrow.
_REFUND_RENDER_SQL = text(
    """
    UPDATE users SET
        day_renders = CASE
            WHEN render_date = :day AND day_renders > 0 THEN day_renders - 1
            ELSE day_renders
        END
    WHERE id = :user_id
    """
)

# Clamped at zero, and the day counter moves only if the row is still on the day
# the slot was taken from — a refund that straddles midnight must not borrow
# from tomorrow's allowance. `day_attempts` is deliberately absent: an attempt
# happened, and no later outcome unhappens it.
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


# Renders are counted the same way and with the same `FOR UPDATE` lock, minus
# every branch: there is no plan to consult (the cap is identical on all of
# them) and no refund path, so one flag is not needed — either the row comes
# back incremented or the cap is already met and the `WHERE` matches nothing.
_COUNT_RENDER_SQL = text(
    """
    WITH before AS (
        SELECT
            id,
            CASE WHEN render_date = :today THEN day_renders ELSE 0 END
                AS render_count
        FROM users
        WHERE id = :user_id
        FOR UPDATE
    )
    UPDATE users SET
        day_renders = before.render_count + 1,
        render_date = :today
    FROM before
    WHERE users.id = before.id
      AND before.render_count < :max_renders
    RETURNING users.day_renders
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
    #: Attempts spent today, this one included. Not refundable.
    day_attempts: int
    _refunded: bool = field(default=False, repr=False)

    def refund(self) -> None:
        """Give the slot back. Safe to call more than once.

        The *attempt* is not given back: the work was started, and that is what
        the attempt cap counts.
        """
        if self._refunded:
            return
        self._refunded = True
        self.db.execute(_REFUND_SQL, {"user_id": self.user_id, "day": self.day})
        self.db.commit()

    @property
    def refunded(self) -> bool:
        return self._refunded


@dataclass
class RenderCount:
    """One spent render, and the only way to give it back.

    Returned by `count_render` so the route can hand the render back in the
    one case that deserves it: refused at the concurrency gate, with no
    browser ever launched. Every other outcome keeps it.
    """

    db: Session
    user_id: uuid.UUID
    #: The Europe/London day the render was counted against.
    day: date
    #: Renders spent today, this one included.
    day_renders: int
    _refunded: bool = field(default=False, repr=False)

    def refund(self) -> None:
        """Give the render back. Safe to call more than once."""
        if self._refunded:
            return
        self._refunded = True
        self.db.execute(
            _REFUND_RENDER_SQL, {"user_id": self.user_id, "day": self.day}
        )
        self.db.commit()

    @property
    def refunded(self) -> bool:
        return self._refunded


def too_many_attempts() -> HTTPException:
    """The refusal for the abuse ceiling. Same for every plan.

    No upsell: an upgrade is the wrong answer to suspected abuse, and a
    subscriber who somehow reaches 20 attempts has nothing left to buy.
    """
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=TOO_MANY_ATTEMPTS_DETAIL,
    )


def too_many_renders() -> HTTPException:
    """The refusal for the render ceiling. Same for every plan.

    No upsell, for the same reason as `too_many_attempts`: a subscriber who
    has rendered 50 PDFs today has nothing left to buy, and a free user is not
    going to be sold a subscription by a wall.
    """
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=TOO_MANY_RENDERS_DETAIL,
    )


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
            "max_attempts": settings.max_daily_attempts,
        },
    ).one_or_none()

    if row is None:
        # The only `WHERE` the row can fail — `get_current_user` just loaded
        # it, so it exists. Over the cap, nothing is written at all, or a
        # looping client would keep topping its own counter up.
        db.rollback()
        raise too_many_attempts()

    if not row.reserved:
        # No slot, so no attempt either: every `SET` above wrote the row's own
        # value back and there is nothing worth keeping. Roll back rather than
        # commit a no-op, so a free user hammering 402s neither accrues
        # attempts nor churns row versions. The plan comes from the row the
        # statement locked, so a subscription that changed mid-request picks
        # the right code.
        db.rollback()
        raise over_limit(row.plan)

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
        day_attempts=row.day_attempts,
    )
    setattr(request.state, STATE_ATTR, reservation)
    return reservation


def count_render(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RenderCount:
    """FastAPI dependency: spend one render, or refuse the request.

    The count is taken before Chromium starts, and a render that then fails or
    overruns its budget keeps it, because launching the browser is where the
    cost is. The returned `RenderCount` exists for the one exception: a request
    turned away by the global concurrency gate, which never launched anything.
    """
    settings = get_settings()
    today = london_today()
    row = db.execute(
        _COUNT_RENDER_SQL,
        {
            "today": today,
            "user_id": user.id,
            "max_renders": settings.max_daily_renders,
        },
    ).one_or_none()

    if row is None:
        # The only `WHERE` that can fail — `get_current_user` just loaded the
        # row. Nothing is written when the cap is met, or a looping client
        # would keep topping its own counter up past the ceiling.
        db.rollback()
        raise too_many_renders()

    db.commit()
    # The ORM row's counters are stale now; the next read goes to the database.
    db.expire(user)
    return RenderCount(
        db=db, user_id=user.id, day=today, day_renders=row.day_renders
    )
