"""add dense capture path points

Revision ID: d534f86c60ad
Revises: c214f4a2b901
Create Date: 2026-08-21 22:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d534f86c60ad"
down_revision: str | None = "c214f4a2b901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capture_path_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("floor_id", sa.Uuid(), nullable=False),
        sa.Column("timestamp_ms", sa.BigInteger(), nullable=False),
        sa.Column("x", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("y", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("heading_deg", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=6, scale=5), nullable=False),
        sa.Column("localization_run_id", sa.Uuid(), nullable=False),
        sa.Column("algorithm", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("timestamp_ms >= 0", name=op.f("ck_capture_path_points_nonnegative_timestamp")),
        sa.CheckConstraint(
            "x >= 0 AND x <= 1 AND y >= 0 AND y <= 1",
            name=op.f("ck_capture_path_points_normalized_position"),
        ),
        sa.CheckConstraint(
            "heading_deg >= 0 AND heading_deg < 360",
            name=op.f("ck_capture_path_points_valid_heading"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_capture_path_points_valid_confidence"),
        ),
        sa.ForeignKeyConstraint(
            ["capture_id"], ["captures.id"],
            name=op.f("fk_capture_path_points_capture_id_captures"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["floor_id"], ["floors.id"],
            name=op.f("fk_capture_path_points_floor_id_floors"),
        ),
        sa.ForeignKeyConstraint(
            ["localization_run_id"], ["processing_jobs.id"],
            name=op.f("fk_capture_path_points_localization_run_id_processing_jobs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capture_path_points")),
        sa.UniqueConstraint(
            "capture_id", "timestamp_ms", name="uq_capture_path_point_timestamp"
        ),
    )
    op.create_index(
        op.f("ix_capture_path_points_capture_id"), "capture_path_points", ["capture_id"]
    )
    op.create_index(
        op.f("ix_capture_path_points_floor_id"), "capture_path_points", ["floor_id"]
    )
    op.create_index(
        op.f("ix_capture_path_points_localization_run_id"),
        "capture_path_points", ["localization_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_capture_path_points_localization_run_id"),
        table_name="capture_path_points",
    )
    op.drop_index(op.f("ix_capture_path_points_floor_id"), table_name="capture_path_points")
    op.drop_index(op.f("ix_capture_path_points_capture_id"), table_name="capture_path_points")
    op.drop_table("capture_path_points")
