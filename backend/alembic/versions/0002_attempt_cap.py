"""users.day_attempts and users.attempt_date

Revision ID: 0002_attempt_cap
Revises: 0001_initial
Create Date: 2026-10-06

The attempt cap. `day_generations` counts papers delivered — it is refunded
when a generation fails or its client disappears — so it cannot bound work
done. These two columns count what was *asked for*, which is never given back.

Added as an ALTER rather than folded into 0001, because 0001 has already been
applied to real databases.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_attempt_cap"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "day_attempts", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.add_column("users", sa.Column("attempt_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "attempt_date")
    op.drop_column("users", "day_attempts")
