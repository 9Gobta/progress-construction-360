import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class BimModelRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version_no: int = Field(ge=1)
    ifc_schema: str
    size_bytes: int = Field(ge=1)
    download_url: str
    created_by_id: uuid.UUID | None
    created_at: datetime


class BimModelListRead(BaseModel):
    active: BimModelRead | None
    versions: list[BimModelRead]


class BimViewpointWrite(BaseModel):
    position_x: float = Field(ge=-10_000_000, le=10_000_000)
    position_y: float = Field(ge=-10_000_000, le=10_000_000)
    position_z: float = Field(ge=-10_000_000, le=10_000_000)
    target_x: float = Field(ge=-10_000_000, le=10_000_000)
    target_y: float = Field(ge=-10_000_000, le=10_000_000)
    target_z: float = Field(ge=-10_000_000, le=10_000_000)
    fov: float = Field(ge=10, le=120)


class BimViewpointRead(BimViewpointWrite):
    id: uuid.UUID
    project_id: uuid.UUID
    model_media_file_id: uuid.UUID
    keyframe_id: uuid.UUID
    updated_by_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
