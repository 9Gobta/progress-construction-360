import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    location: str | None = Field(default=None, max_length=300)
    timezone: str = "Asia/Bangkok"
    description: str | None = Field(default=None, max_length=3000)
    structural_tracking_end_date: date | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    location: str | None
    timezone: str
    description: str | None
    structural_tracking_end_date: date | None
    created_by_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    role: str | None = None


class ProjectScopeUpdate(BaseModel):
    structural_tracking_end_date: date | None


class ProjectMemberCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = "reviewer"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in {"admin", "sub_admin", "reviewer", "viewer"}:
            raise ValueError("role must be admin, sub_admin, reviewer, or viewer")
        return value


class ProjectMemberUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in {"admin", "sub_admin", "reviewer", "viewer"}:
            raise ValueError("role must be admin, sub_admin, reviewer, or viewer")
        return value


class ProjectMemberRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str
    created_at: datetime
