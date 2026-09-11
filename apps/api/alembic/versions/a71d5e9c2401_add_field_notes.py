"""add field notes

Revision ID: a71d5e9c2401
Revises: f4d3a8c91e20
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a71d5e9c2401"
down_revision: str | None = "f4d3a8c91e20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "field_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("floor_id", sa.Uuid(), nullable=False),
        sa.Column("keyframe_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("plan_x", sa.Float(), nullable=True),
        sa.Column("plan_y", sa.Float(), nullable=True),
        sa.Column("panorama_longitude", sa.Float(), nullable=False),
        sa.Column("panorama_latitude", sa.Float(), nullable=False),
        sa.Column("panorama_fov", sa.Float(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN', 'P1', 'P2', 'P3', 'COMPLETED', 'VERIFIED')",
            name=op.f("ck_field_notes_valid_field_note_status"),
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"], name=op.f("fk_field_notes_assignee_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["capture_id"],
            ["captures.id"],
            ondelete="CASCADE",
            name=op.f("fk_field_notes_capture_id_captures"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_field_notes_created_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["floor_id"], ["floors.id"], name=op.f("fk_field_notes_floor_id_floors")
        ),
        sa.ForeignKeyConstraint(
            ["keyframe_id"],
            ["keyframes.id"],
            ondelete="CASCADE",
            name=op.f("fk_field_notes_keyframe_id_keyframes"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_field_notes_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_notes")),
    )
    for column in (
        "project_id",
        "capture_id",
        "floor_id",
        "keyframe_id",
        "status",
        "due_date",
        "assignee_id",
        "created_by_id",
    ):
        op.create_index(op.f(f"ix_field_notes_{column}"), "field_notes", [column])
    op.create_table(
        "field_note_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("field_note_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_field_note_comments_created_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["field_note_id"],
            ["field_notes.id"],
            ondelete="CASCADE",
            name=op.f("fk_field_note_comments_field_note_id_field_notes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_note_comments")),
    )
    op.create_index(
        op.f("ix_field_note_comments_field_note_id"), "field_note_comments", ["field_note_id"]
    )
    op.create_table(
        "field_note_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("field_note_id", sa.Uuid(), nullable=False),
        sa.Column("media_file_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_field_note_attachments_created_by_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["field_note_id"],
            ["field_notes.id"],
            ondelete="CASCADE",
            name=op.f("fk_field_note_attachments_field_note_id_field_notes"),
        ),
        sa.ForeignKeyConstraint(
            ["media_file_id"],
            ["media_files.id"],
            ondelete="CASCADE",
            name=op.f("fk_field_note_attachments_media_file_id_media_files"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_note_attachments")),
        sa.UniqueConstraint("media_file_id", name=op.f("uq_field_note_attachments_media_file_id")),
    )
    op.create_index(
        op.f("ix_field_note_attachments_field_note_id"), "field_note_attachments", ["field_note_id"]
    )


def downgrade() -> None:
    op.drop_table("field_note_attachments")
    op.drop_table("field_note_comments")
    op.drop_table("field_notes")
