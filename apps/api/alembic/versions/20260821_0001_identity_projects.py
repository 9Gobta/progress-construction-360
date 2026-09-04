"""Create identity and project foundation tables.

Revision ID: 20260821_0001
Revises:
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_projects_created_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(op.f("ix_projects_created_by_id"), "projects", ["created_by_id"])

    op.create_table(
        "project_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_members_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_project_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_members")),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )
    op.create_index(op.f("ix_project_members_project_id"), "project_members", ["project_id"])
    op.create_index(op.f("ix_project_members_user_id"), "project_members", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_project_members_user_id"), table_name="project_members")
    op.drop_index(op.f("ix_project_members_project_id"), table_name="project_members")
    op.drop_table("project_members")
    op.drop_index(op.f("ix_projects_created_by_id"), table_name="projects")
    op.drop_table("projects")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
