"""add keyframe warp point flag

Revision ID: f651ad7be3e2
Revises: d534f86c60ad
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f651ad7be3e2"
down_revision: str | None = "d534f86c60ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "keyframes",
        sa.Column("is_warp_point", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("keyframes", "is_warp_point")
