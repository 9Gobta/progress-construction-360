"""add full 360 camera pose

Revision ID: e7c9a1d4f602
Revises: d3f6a90b4c21
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7c9a1d4f602"
down_revision: str | None = "d3f6a90b4c21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("camera_poses", sa.Column("visual_z", sa.Numeric(16, 6), nullable=True))
    op.add_column(
        "camera_poses", sa.Column("visual_ground_z", sa.Numeric(16, 6), nullable=True)
    )
    for axis in "xyzw":
        op.add_column(
            "camera_poses",
            sa.Column(f"orientation_q{axis}", sa.Numeric(18, 12), nullable=True),
        )
    op.add_column("camera_poses", sa.Column("visibility_target_ids", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("camera_poses", "visibility_target_ids")
    for axis in reversed("xyzw"):
        op.drop_column("camera_poses", f"orientation_q{axis}")
    op.drop_column("camera_poses", "visual_ground_z")
    op.drop_column("camera_poses", "visual_z")
