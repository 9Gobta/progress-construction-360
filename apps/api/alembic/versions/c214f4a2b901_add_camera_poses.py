"""add camera poses

Revision ID: c214f4a2b901
Revises: 87a7c87dbddb
Create Date: 2026-08-21 20:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c214f4a2b901"
down_revision: str | None = "87a7c87dbddb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "camera_poses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("keyframe_id", sa.Uuid(), nullable=False),
        sa.Column("floor_id", sa.Uuid(), nullable=False),
        sa.Column("x", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("y", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("heading_deg", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("relative_z_m", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=6, scale=5), nullable=False),
        sa.Column("localization_run_id", sa.Uuid(), nullable=False),
        sa.Column("algorithm", sa.String(length=80), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "x >= 0 AND x <= 1 AND y >= 0 AND y <= 1",
            name=op.f("ck_camera_poses_normalized_position"),
        ),
        sa.CheckConstraint(
            "heading_deg >= 0 AND heading_deg < 360",
            name=op.f("ck_camera_poses_valid_heading"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_camera_poses_valid_confidence"),
        ),
        sa.ForeignKeyConstraint(
            ["floor_id"], ["floors.id"], name=op.f("fk_camera_poses_floor_id_floors")
        ),
        sa.ForeignKeyConstraint(
            ["keyframe_id"],
            ["keyframes.id"],
            name=op.f("fk_camera_poses_keyframe_id_keyframes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["localization_run_id"],
            ["processing_jobs.id"],
            name=op.f("fk_camera_poses_localization_run_id_processing_jobs"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["users.id"], name=op.f("fk_camera_poses_reviewed_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_camera_poses")),
        sa.UniqueConstraint("keyframe_id", name="uq_camera_pose_keyframe"),
    )
    op.create_index(op.f("ix_camera_poses_floor_id"), "camera_poses", ["floor_id"])
    op.create_index(op.f("ix_camera_poses_keyframe_id"), "camera_poses", ["keyframe_id"])
    op.create_index(
        op.f("ix_camera_poses_localization_run_id"),
        "camera_poses",
        ["localization_run_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_camera_poses_localization_run_id"), table_name="camera_poses")
    op.drop_index(op.f("ix_camera_poses_keyframe_id"), table_name="camera_poses")
    op.drop_index(op.f("ix_camera_poses_floor_id"), table_name="camera_poses")
    op.drop_table("camera_poses")
