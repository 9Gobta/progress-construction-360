"""add immutable beam progress labels

Revision ID: f21a1f498c73
Revises: e5a31d6218be
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f21a1f498c73"
down_revision: str | None = "e5a31d6218be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "beam_progress_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("beam_segment_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_keyframe_id", sa.Uuid(), nullable=True),
        sa.Column("progress_percent", sa.Numeric(7, 3), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("entered_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name=op.f("ck_beam_progress_entries_valid_progress"),
        ),
        sa.ForeignKeyConstraint(["beam_segment_id"], ["beam_segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capture_id"], ["captures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entered_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["evidence_keyframe_id"], ["keyframes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_beam_progress_entries")),
    )
    for column in (
        "project_id", "capture_id", "beam_segment_id", "evidence_keyframe_id", "entered_by_id"
    ):
        op.create_index(
            op.f(f"ix_beam_progress_entries_{column}"),
            "beam_progress_entries",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in (
        "entered_by_id", "evidence_keyframe_id", "beam_segment_id", "capture_id", "project_id"
    ):
        op.drop_index(
            op.f(f"ix_beam_progress_entries_{column}"),
            table_name="beam_progress_entries",
        )
    op.drop_table("beam_progress_entries")
