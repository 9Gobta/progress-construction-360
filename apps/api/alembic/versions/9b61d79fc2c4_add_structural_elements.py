"""add plan-aligned IFC structural elements

Revision ID: 9b61d79fc2c4
Revises: 31f0bd9c7a62
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9b61d79fc2c4"
down_revision: str | None = "31f0bd9c7a62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "structural_elements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("floor_id", sa.Uuid(), nullable=True),
        sa.Column("sheet_id", sa.Uuid(), nullable=True),
        sa.Column("ifc_global_id", sa.String(30), nullable=False),
        sa.Column("ifc_type", sa.String(50), nullable=False),
        sa.Column("ifc_storey", sa.String(160), nullable=True),
        sa.Column("element_kind", sa.String(20), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(300), nullable=True),
        sa.Column("geometry_json", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "element_kind IN ('BEAM', 'COLUMN', 'SLAB', 'STAIR', 'FOUNDATION', 'PEDESTAL', 'ROOF')",
            name=op.f("ck_structural_elements_valid_kind"),
        ),
        sa.ForeignKeyConstraint(["floor_id"], ["floors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sheet_id"], ["sheets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_structural_elements")),
        sa.UniqueConstraint("project_id", "ifc_global_id", name="uq_structural_element_ifc"),
    )
    op.create_index(op.f("ix_structural_elements_project_id"), "structural_elements", ["project_id"])
    op.create_index(op.f("ix_structural_elements_floor_id"), "structural_elements", ["floor_id"])
    op.create_index(op.f("ix_structural_elements_sheet_id"), "structural_elements", ["sheet_id"])
    op.create_index(op.f("ix_structural_elements_element_kind"), "structural_elements", ["element_kind"])


def downgrade() -> None:
    op.drop_index(op.f("ix_structural_elements_element_kind"), table_name="structural_elements")
    op.drop_index(op.f("ix_structural_elements_sheet_id"), table_name="structural_elements")
    op.drop_index(op.f("ix_structural_elements_floor_id"), table_name="structural_elements")
    op.drop_index(op.f("ix_structural_elements_project_id"), table_name="structural_elements")
    op.drop_table("structural_elements")
