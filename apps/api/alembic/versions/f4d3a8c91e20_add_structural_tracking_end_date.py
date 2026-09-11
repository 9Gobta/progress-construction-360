"""add structural tracking end date

Revision ID: f4d3a8c91e20
Revises: d8a14c2e7b10
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4d3a8c91e20"
down_revision: str | None = "d8a14c2e7b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("structural_tracking_end_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "structural_tracking_end_date")
