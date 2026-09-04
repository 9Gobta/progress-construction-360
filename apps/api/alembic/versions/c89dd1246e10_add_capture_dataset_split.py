"""add capture dataset split

Revision ID: c89dd1246e10
Revises: f21a1f498c73
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c89dd1246e10"
down_revision: str | None = "f21a1f498c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("captures") as batch_op:
        batch_op.add_column(
            sa.Column(
                "dataset_split",
                sa.String(length=20),
                server_default="DEVELOPMENT",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "valid_dataset_split",
            "dataset_split IN ('DEVELOPMENT', 'HOLDOUT_TEST')",
        )

    captures = sa.table(
        "captures",
        sa.column("captured_at", sa.DateTime(timezone=True)),
        sa.column("dataset_split", sa.String(length=20)),
    )
    op.get_bind().execute(
        captures.update()
        .where(
            sa.func.date(captures.c.captured_at).in_(["2025-12-28", "2026-01-12"])
        )
        .values(dataset_split="HOLDOUT_TEST")
    )


def downgrade() -> None:
    with op.batch_alter_table("captures") as batch_op:
        batch_op.drop_constraint("valid_dataset_split", type_="check")
        batch_op.drop_column("dataset_split")
