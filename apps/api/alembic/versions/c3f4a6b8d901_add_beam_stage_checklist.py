"""add beam progress stage checklist

Revision ID: c3f4a6b8d901
Revises: 9b61d79fc2c4
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3f4a6b8d901"
down_revision: str | None = "9b61d79fc2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "beam_progress_entries",
        sa.Column("stage_status_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("beam_progress_entries", "stage_status_json")
