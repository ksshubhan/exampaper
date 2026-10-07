"""users.cancel_at

Revision ID: 0004_cancel_at
Revises: 0003_render_cap
Create Date: 2026-10-07

When a still-active subscription stops. `/account` needs one date to show a
subscriber who has cancelled but is paid up to the end of the period, and
Stripe can express that cancel either as a `cancel_at` timestamp or as
`cancel_at_period_end` plus the period end — one nullable column holds the
answer either way.

Entitlement does not read this column: a subscription that is `active` with a
cancel scheduled is still on the monthly plan.

An ALTER rather than a change to 0001, because 0001 has already been applied.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_cancel_at"
down_revision = "0003_render_cap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("cancel_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "cancel_at")
