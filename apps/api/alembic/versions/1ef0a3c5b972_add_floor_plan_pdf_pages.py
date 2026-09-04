"""add floor plan PDF page selection

Revision ID: 1ef0a3c5b972
Revises: e8c7b1f3a204
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1ef0a3c5b972"
down_revision: str | None = "e8c7b1f3a204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sheets",
        sa.Column("page_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "sheets",
        sa.Column("page_count", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("sheets", "page_count")
    op.drop_column("sheets", "page_number")
