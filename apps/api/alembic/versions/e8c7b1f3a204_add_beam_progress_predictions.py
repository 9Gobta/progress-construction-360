"""add immutable beam progress predictions

Revision ID: e8c7b1f3a204
Revises: d9302a6e5f41
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8c7b1f3a204"
down_revision: str | None = "d9302a6e5f41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "beam_progress_predictions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("beam_segment_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_keyframe_id", sa.Uuid(), nullable=True),
        sa.Column("progress_percent", sa.Numeric(7, 3), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("dataset_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("training_sample_count", sa.Integer(), nullable=False),
        sa.Column("inference_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)",
            name=op.f("ck_beam_progress_predictions_valid_progress"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_beam_progress_predictions_valid_confidence"),
        ),
        sa.CheckConstraint(
            "training_sample_count >= 0",
            name=op.f("ck_beam_progress_predictions_nonnegative_training_samples"),
        ),
        sa.ForeignKeyConstraint(["beam_segment_id"], ["beam_segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capture_id"], ["captures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_keyframe_id"], ["keyframes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_beam_progress_predictions")),
    )
    for column in ("project_id", "capture_id", "beam_segment_id", "evidence_keyframe_id"):
        op.create_index(
            op.f(f"ix_beam_progress_predictions_{column}"),
            "beam_progress_predictions",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("evidence_keyframe_id", "beam_segment_id", "capture_id", "project_id"):
        op.drop_index(
            op.f(f"ix_beam_progress_predictions_{column}"),
            table_name="beam_progress_predictions",
        )
    op.drop_table("beam_progress_predictions")
