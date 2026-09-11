"""add field note markup

Revision ID: b82c6f1d3502
Revises: a71d5e9c2401
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b82c6f1d3502"
down_revision: str | None = "a71d5e9c2401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "field_notes",
        sa.Column("markup_json", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("field_notes", "markup_json")
