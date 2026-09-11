"""add BIM viewpoints

Revision ID: c2f94a6b7180
Revises: e7c9a1d4f602
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c2f94a6b7180"
down_revision: str | None = "e7c9a1d4f602"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bim_viewpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("model_media_file_id", sa.Uuid(), nullable=False),
        sa.Column("keyframe_id", sa.Uuid(), nullable=False),
        sa.Column("position_x", sa.Numeric(18, 6), nullable=False),
        sa.Column("position_y", sa.Numeric(18, 6), nullable=False),
        sa.Column("position_z", sa.Numeric(18, 6), nullable=False),
        sa.Column("target_x", sa.Numeric(18, 6), nullable=False),
        sa.Column("target_y", sa.Numeric(18, 6), nullable=False),
        sa.Column("target_z", sa.Numeric(18, 6), nullable=False),
        sa.Column("fov", sa.Numeric(7, 3), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("fov >= 10 AND fov <= 120", name="valid_bim_viewpoint_fov"),
        sa.ForeignKeyConstraint(["keyframe_id"], ["keyframes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_media_file_id"], ["media_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_media_file_id", "keyframe_id", name="uq_bim_viewpoint_model_keyframe"),
    )
    op.create_index("ix_bim_viewpoints_project_id", "bim_viewpoints", ["project_id"])
    op.create_index("ix_bim_viewpoints_model_media_file_id", "bim_viewpoints", ["model_media_file_id"])
    op.create_index("ix_bim_viewpoints_keyframe_id", "bim_viewpoints", ["keyframe_id"])


def downgrade() -> None:
    op.drop_index("ix_bim_viewpoints_keyframe_id", table_name="bim_viewpoints")
    op.drop_index("ix_bim_viewpoints_model_media_file_id", table_name="bim_viewpoints")
    op.drop_index("ix_bim_viewpoints_project_id", table_name="bim_viewpoints")
    op.drop_table("bim_viewpoints")
