"""persist capture dataset dates

Revision ID: d9302a6e5f41
Revises: c89dd1246e10
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9302a6e5f41"
down_revision: str | None = "c89dd1246e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capture_dataset_dates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("capture_date", sa.Date(), nullable=False),
        sa.Column("dataset_split", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "dataset_split IN ('DEVELOPMENT', 'HOLDOUT_TEST')",
            name="valid_capture_dataset_date_split",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "capture_date", name="uq_capture_dataset_date"
        ),
    )
    op.create_index(
        op.f("ix_capture_dataset_dates_project_id"),
        "capture_dataset_dates",
        ["project_id"],
        unique=False,
    )

    captures = sa.table(
        "captures",
        sa.column("id", sa.Uuid()),
        sa.column("project_id", sa.Uuid()),
        sa.column("captured_at", sa.DateTime(timezone=True)),
        sa.column("dataset_split", sa.String(length=20)),
    )
    holdout_dates = ["2025-12-28", "2026-01-12"]
    op.get_bind().execute(
        captures.update()
        .where(sa.func.date(captures.c.captured_at).in_(holdout_dates))
        .values(dataset_split="HOLDOUT_TEST")
    )

    assignments = sa.table(
        "capture_dataset_dates",
        sa.column("id", sa.Uuid()),
        sa.column("project_id", sa.Uuid()),
        sa.column("capture_date", sa.Date()),
        sa.column("dataset_split", sa.String(length=20)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    holdout_captures = sa.select(
        captures.c.id,
        captures.c.project_id,
        sa.func.date(captures.c.captured_at),
        captures.c.dataset_split,
        sa.func.current_timestamp(),
    ).where(sa.func.date(captures.c.captured_at).in_(holdout_dates))
    op.get_bind().execute(assignments.insert().from_select(
        ["id", "project_id", "capture_date", "dataset_split", "created_at"],
        holdout_captures,
    ))


def downgrade() -> None:
    op.drop_index(
        op.f("ix_capture_dataset_dates_project_id"),
        table_name="capture_dataset_dates",
    )
    op.drop_table("capture_dataset_dates")
