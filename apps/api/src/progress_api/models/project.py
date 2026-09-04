from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from progress_api.db import Base
from progress_api.models.base import TimestampMixin

if TYPE_CHECKING:
    from progress_api.models.identity import ProjectMember


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Bangkok")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)

    memberships: Mapped[list[ProjectMember]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
