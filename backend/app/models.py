"""ORM models.

One row per Clerk user, plus a log of Stripe event ids for webhook idempotency.
Column names are fixed by docs/accounts-and-payments.md — do not rename them.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

#: The only two plans. `users.plan` is constrained to these.
PLAN_FREE = "free"
PLAN_MONTHLY = "monthly"
PLANS = (PLAN_FREE, PLAN_MONTHLY)


class User(Base):
    """An account holder (a parent). Created on first authenticated request."""

    __tablename__ = "users"
    __table_args__ = (
        # The naming convention expands this to "ck_users_plan".
        CheckConstraint(
            f"plan IN ('{PLAN_FREE}', '{PLAN_MONTHLY}')", name="plan"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    clerk_user_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=PLAN_FREE
    )
    #: Raw Stripe subscription status, stored verbatim.
    subscription_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(
        Text, nullable=True, unique=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        Text, nullable=True, unique=True
    )
    total_generations: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    day_generations: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    #: Europe/London calendar date that `day_generations` counts.
    day_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Generations *started* today — one per reserved slot, on every plan.
    #: Counted separately from `day_generations` because it is never refunded:
    #: a refund gives back the paper, not the right to ask for another one. A
    #: request refused before it reserved anything never reaches this counter.
    day_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    #: Europe/London calendar date that `day_attempts` counts.
    attempt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: PDFs rendered today. Like `day_attempts` it counts work done and is
    #: never refunded — a render that fails still cost a Chromium launch.
    #: Separate from the generation counters because rendering reserves no
    #: slot: re-downloading a paper is free, but not unlimited.
    day_renders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    #: Europe/London calendar date that `day_renders` counts.
    render_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email} plan={self.plan}>"


class StripeEvent(Base):
    """A Stripe event id we have already processed. Makes the webhook idempotent."""

    __tablename__ = "stripe_events"

    #: The Stripe event id, e.g. "evt_1Abc...".
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
