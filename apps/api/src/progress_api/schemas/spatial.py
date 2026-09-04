import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FloorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    level_index: int = Field(ge=-10, le=300)
    elevation_m: Decimal | None = Field(default=None, ge=-1000, le=10000)
    available_from: date | None = None


class FloorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    level_index: int
    elevation_m: Decimal | None
    available_from: date | None
    has_plan: bool = False
    created_at: datetime
    updated_at: datetime


class FloorPlanInfo(BaseModel):
    filename: str | None
    content_type: str
    page_number: int = Field(ge=1)
    page_count: int = Field(ge=1)
    width_px: int | None = Field(default=None, gt=0)
    height_px: int | None = Field(default=None, gt=0)


class FloorPlanPageRequest(BaseModel):
    page_number: int = Field(ge=1)


class BeamSegmentInput(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    beam_type: str | None = Field(default=None, max_length=50)
    start_x: Decimal = Field(ge=0, le=1)
    start_y: Decimal = Field(ge=0, le=1)
    end_x: Decimal = Field(ge=0, le=1)
    end_y: Decimal = Field(ge=0, le=1)
    length_m: Decimal | None = Field(default=None, gt=0)


class BeamSegmentSetRequest(BaseModel):
    sheet_name: str = Field(default="แปลนโครงสร้างชั้น 1", min_length=1, max_length=200)
    segments: list[BeamSegmentInput] = Field(min_length=1, max_length=1000)


class BeamSegmentLengthUpdate(BaseModel):
    length_m: Decimal = Field(gt=0, le=10000)


class StructuralElementAreaUpdate(BaseModel):
    area_m2: Decimal = Field(gt=0, le=1000000)


class BeamSegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sheet_id: uuid.UUID
    code: str
    beam_type: str | None
    start_x: Decimal
    start_y: Decimal
    end_x: Decimal
    end_y: Decimal
    length_m: Decimal | None
    source: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StructuralElementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    floor_id: uuid.UUID | None
    sheet_id: uuid.UUID | None
    ifc_global_id: str
    ifc_type: str
    ifc_storey: str | None
    element_kind: str
    code: str
    name: str | None
    geometry_json: dict[str, object]
    source: str
    is_active: bool
