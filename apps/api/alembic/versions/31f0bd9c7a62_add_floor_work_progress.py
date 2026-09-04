"""add floor work catalog and progress observations

Revision ID: 31f0bd9c7a62
Revises: 1ef0a3c5b972
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "31f0bd9c7a62"
down_revision: str | None = "1ef0a3c5b972"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "floor_work_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("floor_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("discipline", sa.String(30), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("weight", sa.Numeric(9, 4), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("weight > 0", name=op.f("ck_floor_work_items_positive_weight")),
        sa.ForeignKeyConstraint(["floor_id"], ["floors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_floor_work_items")),
        sa.UniqueConstraint("floor_id", "code", name="uq_floor_work_item_code"),
    )
    for column in ("project_id", "floor_id", "discipline"):
        op.create_index(op.f(f"ix_floor_work_items_{column}"), "floor_work_items", [column])
    for table in ("work_progress_entries", "work_progress_predictions"):
        prediction = table.endswith("predictions")
        columns = [
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("capture_id", sa.Uuid(), nullable=False),
            sa.Column("work_item_id", sa.Uuid(), nullable=False),
            sa.Column("evidence_keyframe_id", sa.Uuid(), nullable=True),
            sa.Column("progress_percent", sa.Numeric(7, 3), nullable=prediction),
        ]
        if prediction:
            columns += [
                sa.Column("status", sa.String(30), nullable=False),
                sa.Column("confidence", sa.Numeric(6, 5), nullable=False),
                sa.Column("needs_review", sa.Boolean(), nullable=False),
                sa.Column("model_version", sa.String(100), nullable=False),
                sa.Column("dataset_fingerprint", sa.String(64), nullable=False),
                sa.Column("training_sample_count", sa.Integer(), nullable=False),
                sa.Column("inference_ms", sa.Integer(), nullable=False),
            ]
        else:
            columns += [
                sa.Column("note", sa.Text(), nullable=True),
                sa.Column("entered_by_id", sa.Uuid(), nullable=False),
            ]
        columns += [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)]
        constraints = [
            sa.CheckConstraint(
                "progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)"
                if prediction else "progress_percent >= 0 AND progress_percent <= 100",
                name=op.f(f"ck_{table}_valid_progress"),
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["capture_id"], ["captures.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["work_item_id"], ["floor_work_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["evidence_keyframe_id"], ["keyframes.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        ]
        if prediction:
            constraints += [
                sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name=op.f(f"ck_{table}_valid_confidence")),
                sa.CheckConstraint("training_sample_count >= 0", name=op.f(f"ck_{table}_nonnegative_training_samples")),
            ]
        else:
            constraints += [sa.ForeignKeyConstraint(["entered_by_id"], ["users.id"])]
        op.create_table(table, *columns, *constraints)
        for column in ("project_id", "capture_id", "work_item_id", "evidence_keyframe_id"):
            op.create_index(op.f(f"ix_{table}_{column}"), table, [column])
        if not prediction:
            op.create_index(op.f(f"ix_{table}_entered_by_id"), table, ["entered_by_id"])


def downgrade() -> None:
    op.drop_table("work_progress_predictions")
    op.drop_table("work_progress_entries")
    op.drop_table("floor_work_items")
