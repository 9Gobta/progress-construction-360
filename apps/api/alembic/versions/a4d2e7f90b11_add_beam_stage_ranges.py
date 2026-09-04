"""add beam progress stage ranges

Revision ID: a4d2e7f90b11
Revises: c3f4a6b8d901
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4d2e7f90b11"
down_revision: str | None = "c3f4a6b8d901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "beam_progress_entries",
        sa.Column("stage_ranges_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("beam_progress_entries", "stage_ranges_json")
