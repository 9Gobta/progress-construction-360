from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from progress_api.db import Base
from progress_api.models.base import utc_now


class HumanProgressEntry(Base):
    """Immutable human observation used to compare people, AI, and plan."""

    __tablename__ = "human_progress_entries"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="valid_progress",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("activities.id", ondelete="CASCADE"), index=True
    )
    capture_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="SET NULL"), nullable=True, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    progress_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class BeamProgressEntry(Base):
    """Immutable human label for one beam segment in one capture."""

    __tablename__ = "beam_progress_entries"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="valid_progress",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    beam_segment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("beam_segments.id", ondelete="CASCADE"), index=True
    )
    evidence_keyframe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("keyframes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    progress_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3))
    stage_status_json: Mapped[dict[str, bool] | None] = mapped_column(JSON, nullable=True)
    stage_ranges_json: Mapped[dict[str, list[dict[str, float]]] | None] = mapped_column(
        JSON, nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class StructuralElementProgressEntry(Base):
    """Immutable human progress label for one plan-aligned structural element."""

    __tablename__ = "structural_element_progress_entries"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="valid_progress",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    structural_element_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("structural_elements.id", ondelete="CASCADE"), index=True
    )
    evidence_keyframe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("keyframes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    progress_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3))
    stage_status_json: Mapped[dict[str, bool]] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class BeamProgressPrediction(Base):
    """Immutable AI inference for one beam segment and capture."""

    __tablename__ = "beam_progress_predictions"
    __table_args__ = (
        CheckConstraint(
            "progress_percent IS NULL OR "
            "(progress_percent >= 0 AND progress_percent <= 100)",
            name="valid_progress",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="valid_confidence",
        ),
        CheckConstraint("training_sample_count >= 0", name="nonnegative_training_samples"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    beam_segment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("beam_segments.id", ondelete="CASCADE"), index=True
    )
    evidence_keyframe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("keyframes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    progress_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5))
    needs_review: Mapped[bool] = mapped_column(default=False)
    model_version: Mapped[str] = mapped_column(String(100))
    dataset_fingerprint: Mapped[str] = mapped_column(String(64))
    training_sample_count: Mapped[int] = mapped_column(Integer)
    inference_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class FloorWorkItem(Base):
    """A measurable structural or architectural work package on one floor."""

    __tablename__ = "floor_work_items"
    __table_args__ = (
        UniqueConstraint("floor_id", "code", name="uq_floor_work_item_code"),
        CheckConstraint("weight > 0", name="positive_weight"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    floor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("floors.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(40))
    discipline: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(300))
    unit: Mapped[str] = mapped_column(String(30), default="percent")
    weight: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal("1"))
    sequence: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class WorkProgressEntry(Base):
    """Immutable human progress observation for one floor work item."""

    __tablename__ = "work_progress_entries"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="valid_progress",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("floor_work_items.id", ondelete="CASCADE"), index=True
    )
    evidence_keyframe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("keyframes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    progress_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class WorkProgressPrediction(Base):
    """Immutable AI estimate for one floor work item and capture."""

    __tablename__ = "work_progress_predictions"
    __table_args__ = (
        CheckConstraint(
            "progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)",
            name="valid_progress",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="valid_confidence"),
        CheckConstraint("training_sample_count >= 0", name="nonnegative_training_samples"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("floor_work_items.id", ondelete="CASCADE"), index=True
    )
    evidence_keyframe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("keyframes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    progress_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True)
    model_version: Mapped[str] = mapped_column(String(100))
    dataset_fingerprint: Mapped[str] = mapped_column(String(64))
    training_sample_count: Mapped[int] = mapped_column(Integer)
    inference_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
