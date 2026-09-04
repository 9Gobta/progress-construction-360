"""add immutable visual pose coordinates

Revision ID: b86154cb75a1
Revises: f651ad7be3e2
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b86154cb75a1"
down_revision: str | None = "f651ad7be3e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("camera_poses", sa.Column("visual_x", sa.Numeric(16, 6), nullable=True))
    op.add_column("camera_poses", sa.Column("visual_y", sa.Numeric(16, 6), nullable=True))
    op.add_column(
        "camera_poses",
        sa.Column("visual_heading_deg", sa.Numeric(8, 3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("camera_poses", "visual_heading_deg")
    op.drop_column("camera_poses", "visual_y")
    op.drop_column("camera_poses", "visual_x")
