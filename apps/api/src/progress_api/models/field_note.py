from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from progress_api.db import Base
from progress_api.models.base import TimestampMixin, utc_now


class FieldNote(TimestampMixin, Base):
    __tablename__ = "field_notes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'P1', 'P2', 'P3', 'COMPLETED', 'VERIFIED')",
            name="valid_field_note_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    floor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("floors.id"), index=True)
    keyframe_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("keyframes.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    markup_json: Mapped[str] = mapped_column(Text, default="[]")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )
    plan_x: Mapped[float | None] = mapped_column(nullable=True)
    plan_y: Mapped[float | None] = mapped_column(nullable=True)
    panorama_longitude: Mapped[float] = mapped_column(default=0)
    panorama_latitude: Mapped[float] = mapped_column(default=0)
    panorama_fov: Mapped[float] = mapped_column(default=70)
    created_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)


class FieldNoteComment(Base):
    __tablename__ = "field_note_comments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    field_note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("field_notes.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FieldNoteAttachment(Base):
    __tablename__ = "field_note_attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    field_note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("field_notes.id", ondelete="CASCADE"), index=True
    )
    media_file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_files.id", ondelete="CASCADE"), unique=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
