"""add image-verified portal directions

Revision ID: c91f420a782e
Revises: b82c6f1d3502
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c91f420a782e"
down_revision: str | None = "b82c6f1d3502"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "camera_poses",
        sa.Column("portal_directions_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("camera_poses", "portal_directions_json")
