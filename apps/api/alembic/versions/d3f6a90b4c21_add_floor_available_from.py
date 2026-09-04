"""add floor availability date

Revision ID: d3f6a90b4c21
Revises: b7e1c5a9034d
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3f6a90b4c21"
down_revision: str | None = "b7e1c5a9034d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("floors", sa.Column("available_from", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("floors", "available_from")
