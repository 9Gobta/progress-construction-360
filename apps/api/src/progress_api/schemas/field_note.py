import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

FieldNoteStatus = Literal["OPEN", "P1", "P2", "P3", "COMPLETED", "VERIFIED"]


class FieldNoteWrite(BaseModel):
    capture_id: uuid.UUID
    floor_id: uuid.UUID
    keyframe_id: uuid.UUID
    title: str = Field(min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=5000)
    status: FieldNoteStatus = "OPEN"
    due_date: date | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    assignee_id: uuid.UUID | None = None
    plan_x: float | None = Field(default=None, ge=0, le=1)
    plan_y: float | None = Field(default=None, ge=0, le=1)
    panorama_longitude: float = Field(default=0, ge=-180, le=180)
    panorama_latitude: float = Field(default=0, ge=-90, le=90)
    panorama_fov: float = Field(default=70, ge=10, le=120)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        clean = []
        for value in values:
            tag = value.strip()[:50]
            if tag and tag.casefold() not in {item.casefold() for item in clean}:
                clean.append(tag)
        return clean


class FieldNoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=5000)
    status: FieldNoteStatus | None = None
    due_date: date | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    assignee_id: uuid.UUID | None = None
    markup_paths: list[list[tuple[float, float]]] | None = Field(default=None, max_length=100)

    @field_validator("tags")
    @classmethod
    def normalize_optional_tags(cls, values: list[str] | None) -> list[str] | None:
        return FieldNoteWrite.normalize_tags(values) if values is not None else None

    @field_validator("markup_paths")
    @classmethod
    def validate_markup_paths(
        cls, paths: list[list[tuple[float, float]]] | None
    ) -> list[list[tuple[float, float]]] | None:
        if paths is None:
            return None
        if sum(len(path) for path in paths) > 5000:
            raise ValueError("markup may contain at most 5000 points")
        if any(x < 0 or x > 1000 or y < 0 or y > 1000 for path in paths for x, y in path):
            raise ValueError("markup coordinates must be between 0 and 1000")
        return paths


class FieldNoteCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=3000)


class FieldNoteCommentRead(BaseModel):
    id: uuid.UUID
    body: str
    created_by_id: uuid.UUID
    created_by_name: str
    created_at: datetime


class FieldNoteAttachmentRead(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    download_url: str


class FieldNoteRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    capture_id: uuid.UUID
    capture_date: datetime
    floor_id: uuid.UUID
    floor_name: str
    keyframe_id: uuid.UUID
    keyframe_timestamp_ms: int
    image_url: str
    title: str
    description: str | None
    status: FieldNoteStatus
    due_date: date | None
    tags: list[str]
    markup_paths: list[list[tuple[float, float]]]
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    plan_x: float | None
    plan_y: float | None
    panorama_longitude: float
    panorama_latitude: float
    panorama_fov: float
    created_by_id: uuid.UUID
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    comments: list[FieldNoteCommentRead]
    attachments: list[FieldNoteAttachmentRead]
