"""add path control points

Revision ID: a942d781d811
Revises: b86154cb75a1
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a942d781d811"
down_revision: str | None = "b86154cb75a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "path_control_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("keyframe_id", sa.Uuid(), nullable=False),
        sa.Column("floor_id", sa.Uuid(), nullable=False),
        sa.Column("x", sa.Numeric(8, 6), nullable=False),
        sa.Column("y", sa.Numeric(8, 6), nullable=False),
        sa.Column("error_normalized", sa.Numeric(10, 8), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "x >= 0 AND x <= 1 AND y >= 0 AND y <= 1",
            name=op.f("ck_path_control_points_normalized_position"),
        ),
        sa.CheckConstraint(
            "error_normalized >= 0",
            name=op.f("ck_path_control_points_nonnegative_error"),
        ),
        sa.ForeignKeyConstraint(
            ["capture_id"], ["captures.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"]
        ),
        sa.ForeignKeyConstraint(["floor_id"], ["floors.id"]),
        sa.ForeignKeyConstraint(
            ["keyframe_id"], ["keyframes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_path_control_points")),
        sa.UniqueConstraint(
            "capture_id",
            "keyframe_id",
            name="uq_path_control_point_capture_keyframe",
        ),
    )
    op.create_index(
        op.f("ix_path_control_points_capture_id"),
        "path_control_points",
        ["capture_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_path_control_points_floor_id"),
        "path_control_points",
        ["floor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_path_control_points_keyframe_id"),
        "path_control_points",
        ["keyframe_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_path_control_points_keyframe_id"),
        table_name="path_control_points",
    )
    op.drop_index(
        op.f("ix_path_control_points_floor_id"),
        table_name="path_control_points",
    )
    op.drop_index(
        op.f("ix_path_control_points_capture_id"),
        table_name="path_control_points",
    )
    op.drop_table("path_control_points")
