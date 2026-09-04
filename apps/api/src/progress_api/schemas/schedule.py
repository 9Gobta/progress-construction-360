import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SchedulePreviewActivity(BaseModel):
    source_row_no: int
    name: str
    wbs: str
    parent_wbs: str | None
    planned_start: datetime
    planned_finish: datetime
    is_summary: bool


class SchedulePreviewRead(BaseModel):
    filename: str
    checksum: str
    sheet_name: str
    row_count: int
    used_baseline_dates: bool
    warnings: list[str]
    activities: list[SchedulePreviewActivity]


class ScheduleVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version_no: int
    source_type: str
    is_baseline: bool
    imported_by_id: uuid.UUID
    imported_at: datetime
    row_count: int
    checksum: str
    status: str


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    schedule_version_id: uuid.UUID
    parent_activity_id: uuid.UUID | None
    wbs: str
    name: str
    planned_start: datetime
    planned_finish: datetime
    is_summary: bool
    source_row_no: int
    created_at: datetime
