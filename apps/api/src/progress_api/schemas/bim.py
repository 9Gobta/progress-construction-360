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
