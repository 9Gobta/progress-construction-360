"""add structural element progress

Revision ID: b7e1c5a9034d
Revises: a4d2e7f90b11
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e1c5a9034d"
down_revision: str | None = "a4d2e7f90b11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "structural_element_progress_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("structural_element_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_keyframe_id", sa.Uuid(), nullable=True),
        sa.Column("progress_percent", sa.Numeric(7, 3), nullable=False),
        sa.Column("stage_status_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("entered_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="valid_progress",
        ),
        sa.ForeignKeyConstraint(["capture_id"], ["captures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entered_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["evidence_keyframe_id"], ["keyframes.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["structural_element_id"], ["structural_elements.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "project_id",
        "capture_id",
        "structural_element_id",
        "evidence_keyframe_id",
        "entered_by_id",
    ):
        op.create_index(
            f"ix_structural_element_progress_entries_{column}",
            "structural_element_progress_entries",
            [column],
        )


def downgrade() -> None:
    op.drop_table("structural_element_progress_entries")
