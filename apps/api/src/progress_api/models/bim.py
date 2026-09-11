from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from progress_api.db import Base
from progress_api.models.base import TimestampMixin


class BimViewpoint(TimestampMixin, Base):
    """A reviewer-authored IFC camera bookmark for one Virtual Tour station."""

    __tablename__ = "bim_viewpoints"
    __table_args__ = (
        UniqueConstraint(
            "model_media_file_id",
            "keyframe_id",
            name="uq_bim_viewpoint_model_keyframe",
        ),
        CheckConstraint("fov >= 10 AND fov <= 120", name="valid_bim_viewpoint_fov"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    model_media_file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_files.id", ondelete="CASCADE"), index=True
    )
    keyframe_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("keyframes.id", ondelete="CASCADE"), index=True
    )
    position_x: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    position_y: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    position_z: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    target_x: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    target_y: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    target_z: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    fov: Mapped[Decimal] = mapped_column(Numeric(7, 3))
    updated_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
