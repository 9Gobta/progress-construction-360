from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from progress_api.db import Base
from progress_api.models.base import TimestampMixin


class Floor(TimestampMixin, Base):
    __tablename__ = "floors"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_floor_project_name"),
        UniqueConstraint("project_id", "level_index", name="uq_floor_project_level"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    level_index: Mapped[int] = mapped_column(Integer)
    elevation_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    available_from: Mapped[date | None] = mapped_column(Date, nullable=True)


class Room(TimestampMixin, Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("floor_id", "name", name="uq_room_floor_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    floor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("floors.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    polygon_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)


class Sheet(TimestampMixin, Base):
    __tablename__ = "sheets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    floor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("floors.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    sheet_type: Mapped[str] = mapped_column(String(30))
    source_media_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_files.id"), nullable=True
    )
    preview_media_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_files.id"), nullable=True
    )
    width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    scale_m_per_normalized_unit: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class GridAxis(Base):
    __tablename__ = "grid_axes"
    __table_args__ = (
        UniqueConstraint("sheet_id", "axis_group", "label", name="uq_grid_axis_label"),
        CheckConstraint(
            "start_x >= 0 AND start_x <= 1 AND start_y >= 0 AND start_y <= 1 "
            "AND end_x >= 0 AND end_x <= 1 AND end_y >= 0 AND end_y <= 1",
            name="normalized_coordinates",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sheet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sheets.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(30))
    axis_group: Mapped[str] = mapped_column(String(20))
    start_x: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    start_y: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    end_x: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    end_y: Mapped[Decimal] = mapped_column(Numeric(8, 6))


class BeamSegment(TimestampMixin, Base):
    __tablename__ = "beam_segments"
    __table_args__ = (
        UniqueConstraint("sheet_id", "code", name="uq_beam_segment_code"),
        CheckConstraint(
            "start_x >= 0 AND start_x <= 1 AND start_y >= 0 AND start_y <= 1 "
            "AND end_x >= 0 AND end_x <= 1 AND end_y >= 0 AND end_y <= 1",
            name="normalized_coordinates",
        ),
        CheckConstraint("length_m IS NULL OR length_m > 0", name="positive_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sheet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sheets.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(100))
    beam_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_x: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    start_y: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    end_x: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    end_y: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    length_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="MANUAL")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StructuralElement(TimestampMixin, Base):
    """A plan-aligned physical item extracted from the project's IFC model."""

    __tablename__ = "structural_elements"
    __table_args__ = (
        UniqueConstraint("project_id", "ifc_global_id", name="uq_structural_element_ifc"),
        CheckConstraint(
            "element_kind IN ('BEAM', 'COLUMN', 'SLAB', 'STAIR', 'FOUNDATION', 'PEDESTAL', 'ROOF')",
            name="valid_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    floor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("floors.id", ondelete="CASCADE"), nullable=True, index=True
    )
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sheets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ifc_global_id: Mapped[str] = mapped_column(String(30))
    ifc_type: Mapped[str] = mapped_column(String(50))
    ifc_storey: Mapped[str | None] = mapped_column(String(160), nullable=True)
    element_kind: Mapped[str] = mapped_column(String(20), index=True)
    code: Mapped[str] = mapped_column(String(120))
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    geometry_json: Mapped[dict[str, object]] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(30), default="IFC_PLAN_ALIGNED")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
