from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from progress_api.db import Base
from progress_api.models.base import utc_now


class ScheduleVersion(Base):
    __tablename__ = "schedule_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_schedule_project_version"),
        UniqueConstraint("project_id", "checksum", name="uq_schedule_project_checksum"),
        CheckConstraint("row_count >= 0", name="nonnegative_row_count"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    version_no: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(20))
    source_media_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_files.id"), nullable=True
    )
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    imported_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    row_count: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="VALIDATING")


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("schedule_version_id", "wbs", name="uq_activity_schedule_wbs"),
        CheckConstraint("planned_finish >= planned_start", name="valid_dates"),
        CheckConstraint(
            "percent_complete_source IS NULL OR "
            "(percent_complete_source >= 0 AND percent_complete_source <= 100)",
            name="valid_percent_complete",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    schedule_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("schedule_versions.id", ondelete="CASCADE"), index=True
    )
    parent_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("activities.id"), nullable=True
    )
    wbs: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(500))
    planned_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    planned_finish: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    percent_complete_source: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 3), nullable=True
    )
    is_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    source_row_no: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
