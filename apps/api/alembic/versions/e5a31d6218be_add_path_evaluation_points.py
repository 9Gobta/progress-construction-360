"""add held-out path evaluation points

Revision ID: e5a31d6218be
Revises: a942d781d811
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5a31d6218be"
down_revision: str | None = "a942d781d811"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "path_evaluation_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("keyframe_id", sa.Uuid(), nullable=False),
        sa.Column("floor_id", sa.Uuid(), nullable=False),
        sa.Column("localization_run_id", sa.Uuid(), nullable=False),
        sa.Column("target_x", sa.Numeric(8, 6), nullable=False),
        sa.Column("target_y", sa.Numeric(8, 6), nullable=False),
        sa.Column("predicted_x", sa.Numeric(8, 6), nullable=False),
        sa.Column("predicted_y", sa.Numeric(8, 6), nullable=False),
        sa.Column("error_normalized", sa.Numeric(10, 8), nullable=False),
        sa.Column("tolerance_normalized", sa.Numeric(8, 6), nullable=False),
        sa.Column("is_within_tolerance", sa.Boolean(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_x >= 0 AND target_x <= 1 AND target_y >= 0 AND target_y <= 1 "
            "AND predicted_x >= 0 AND predicted_x <= 1 "
            "AND predicted_y >= 0 AND predicted_y <= 1",
            name=op.f("ck_path_evaluation_points_normalized_positions"),
        ),
        sa.CheckConstraint(
            "error_normalized >= 0",
            name=op.f("ck_path_evaluation_points_nonnegative_error"),
        ),
        sa.CheckConstraint(
            "tolerance_normalized > 0 AND tolerance_normalized <= 1",
            name=op.f("ck_path_evaluation_points_valid_tolerance"),
        ),
        sa.ForeignKeyConstraint(["capture_id"], ["captures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["floor_id"], ["floors.id"]),
        sa.ForeignKeyConstraint(["keyframe_id"], ["keyframes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["localization_run_id"], ["processing_jobs.id"]),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_path_evaluation_points")),
        sa.UniqueConstraint(
            "capture_id", "keyframe_id", name="uq_path_evaluation_capture_keyframe"
        ),
    )
    for column in ("capture_id", "keyframe_id", "floor_id", "localization_run_id"):
        op.create_index(
            op.f(f"ix_path_evaluation_points_{column}"),
            "path_evaluation_points",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("localization_run_id", "floor_id", "keyframe_id", "capture_id"):
        op.drop_index(
            op.f(f"ix_path_evaluation_points_{column}"),
            table_name="path_evaluation_points",
        )
    op.drop_table("path_evaluation_points")
