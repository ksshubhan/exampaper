"""users.day_renders and users.render_date

Revision ID: 0003_render_cap
Revises: 0002_attempt_cap
Create Date: 2026-10-06

The render cap. `/api/render-pdf` reserves no generation slot — re-downloading
a paper is free by design — so none of the existing counters bound it, and it
is the most expensive endpoint we have: one headless Chromium per call. These
two columns count renders started per Europe/London day, and like
`day_attempts` they are never given back.

An ALTER rather than a change to 0001, because 0001 has already been applied.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_render_cap"
down_revision = "0002_attempt_cap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("day_renders", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("users", sa.Column("render_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "render_date")
    op.drop_column("users", "day_renders")
