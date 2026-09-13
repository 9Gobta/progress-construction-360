from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from progress_api.db import Base
from progress_api.models.base import TimestampMixin, utc_now


class MediaFile(Base):
    __tablename__ = "media_files"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_media_object"),
        CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    media_kind: Mapped[str] = mapped_column(String(30))
    bucket: Mapped[str] = mapped_column(String(100))
    object_key: Mapped[str] = mapped_column(String(1000))
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str] = mapped_column(String(150))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upload_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class MultipartUploadSession(Base):
    __tablename__ = "multipart_upload_sessions"
    __table_args__ = (
        CheckConstraint("part_size_bytes >= 5242880", name="valid_part_size"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    media_file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_files.id", ondelete="CASCADE"), unique=True
    )
    provider_upload_id: Mapped[str] = mapped_column(String(1000), unique=True)
    part_size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="INITIATED")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Capture(TimestampMixin, Base):
    __tablename__ = "captures"
    __table_args__ = (
        CheckConstraint(
            "start_x >= 0 AND start_x <= 1 AND start_y >= 0 AND start_y <= 1",
            name="normalized_start",
        ),
        CheckConstraint(
            "dataset_split IN ('DEVELOPMENT', 'HOLDOUT_TEST')",
            name="valid_dataset_split",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_files.id"), unique=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    captured_by_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_floor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("floors.id"))
    start_x: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    start_y: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_split: Mapped[str] = mapped_column(String(20), default="DEVELOPMENT")
    status: Mapped[str] = mapped_column(String(30), default="UPLOADING")
    created_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))


class CaptureDatasetDate(Base):
    """Persistent project/date split assignment that survives Capture replacement."""

    __tablename__ = "capture_dataset_dates"
    __table_args__ = (
        UniqueConstraint("project_id", "capture_date", name="uq_capture_dataset_date"),
        CheckConstraint(
            "dataset_split IN ('DEVELOPMENT', 'HOLDOUT_TEST')",
            name="valid_capture_dataset_date_split",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    capture_date: Mapped[date] = mapped_column(Date)
    dataset_split: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_processing_job_idempotency"),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="valid_progress",
        ),
        CheckConstraint("attempt_no >= 1", name="positive_attempt"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    progress_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), default=0)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    pipeline_version: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class VideoMetadata(Base):
    __tablename__ = "video_metadata"
    __table_args__ = (
        CheckConstraint("duration_ms > 0", name="positive_duration"),
        CheckConstraint("width_px > 0 AND height_px > 0", name="positive_dimensions"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    media_file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_files.id", ondelete="CASCADE"), unique=True
    )
    format_name: Mapped[str] = mapped_column(String(100))
    codec_name: Mapped[str] = mapped_column(String(100))
    duration_ms: Mapped[int] = mapped_column(BigInteger)
    width_px: Mapped[int] = mapped_column(Integer)
    height_px: Mapped[int] = mapped_column(Integer)
    fps: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    is_equirectangular: Mapped[bool] = mapped_column(Boolean)
    ffprobe_json: Mapped[str] = mapped_column(Text)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Keyframe(Base):
    __tablename__ = "keyframes"
    __table_args__ = (
        UniqueConstraint("capture_id", "frame_index", name="uq_keyframe_capture_frame"),
        UniqueConstraint("capture_id", "timestamp_ms", name="uq_keyframe_capture_timestamp"),
        CheckConstraint("frame_index >= 0", name="nonnegative_frame_index"),
        CheckConstraint("timestamp_ms >= 0", name="nonnegative_timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    media_file_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("media_files.id"))
    frame_index: Mapped[int] = mapped_column(Integer)
    timestamp_ms: Mapped[int] = mapped_column(BigInteger)
    quality_status: Mapped[str] = mapped_column(String(20), default="USABLE")
    is_warp_point: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CameraPose(TimestampMixin, Base):
    """A keyframe position on a floor plan produced by localization or human review."""

    __tablename__ = "camera_poses"
    __table_args__ = (
        UniqueConstraint("keyframe_id", name="uq_camera_pose_keyframe"),
        CheckConstraint(
            "x >= 0 AND x <= 1 AND y >= 0 AND y <= 1",
            name="normalized_position",
        ),
        CheckConstraint(
            "heading_deg >= 0 AND heading_deg < 360",
            name="valid_heading",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="valid_confidence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    keyframe_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("keyframes.id", ondelete="CASCADE"), index=True
    )
    floor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("floors.id"), index=True)
    x: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    y: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    heading_deg: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    # Immutable coordinates in the SfM reconstruction plane. They keep visual
    # navigation independent from later human edits on the floor plan.
    visual_x: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), nullable=True)
    visual_y: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), nullable=True)
    visual_heading_deg: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3), nullable=True
    )
    # Full metric camera pose in the reconstruction frame.  Keeping the source
    # quaternion avoids flattening a 360 camera to yaw-only navigation.
    visual_z: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), nullable=True)
    visual_ground_z: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 6), nullable=True
    )
    orientation_qx: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12), nullable=True
    )
    orientation_qy: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12), nullable=True
    )
    orientation_qz: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12), nullable=True
    )
    orientation_qw: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12), nullable=True
    )
    # JSON UUID list produced by ray/mesh visibility tests for this station.
    visibility_target_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON map keyed by destination keyframe id. Bearings are measured from
    # the actual source/target panorama pair with an essential-matrix check.
    portal_directions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    relative_z_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5))
    localization_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("processing_jobs.id"), index=True
    )
    algorithm: Mapped[str] = mapped_column(String(80))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CapturePathPoint(Base):
    """A dense camera track sample, independent from the sparse viewer warp points."""

    __tablename__ = "capture_path_points"
    __table_args__ = (
        UniqueConstraint(
            "capture_id", "timestamp_ms", name="uq_capture_path_point_timestamp"
        ),
        CheckConstraint("timestamp_ms >= 0", name="nonnegative_timestamp"),
        CheckConstraint(
            "x >= 0 AND x <= 1 AND y >= 0 AND y <= 1",
            name="normalized_position",
        ),
        CheckConstraint(
            "heading_deg >= 0 AND heading_deg < 360",
            name="valid_heading",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="valid_confidence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    floor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("floors.id"), index=True)
    timestamp_ms: Mapped[int] = mapped_column(BigInteger)
    x: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    y: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    heading_deg: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5))
    localization_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("processing_jobs.id"), index=True
    )
    algorithm: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class PathControlPoint(Base):
    """Human calibration anchor linking one Stella pose to a plan location."""

    __tablename__ = "path_control_points"
    __table_args__ = (
        UniqueConstraint(
            "capture_id", "keyframe_id", name="uq_path_control_point_capture_keyframe"
        ),
        CheckConstraint(
            "x >= 0 AND x <= 1 AND y >= 0 AND y <= 1",
            name="normalized_position",
        ),
        CheckConstraint("error_normalized >= 0", name="nonnegative_error"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    keyframe_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("keyframes.id", ondelete="CASCADE"), index=True
    )
    floor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("floors.id"), index=True)
    x: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    y: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    error_normalized: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=0)
    created_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class PathEvaluationPoint(Base):
    """Held-out localization observation captured without changing the path."""

    __tablename__ = "path_evaluation_points"
    __table_args__ = (
        UniqueConstraint(
            "capture_id", "keyframe_id", name="uq_path_evaluation_capture_keyframe"
        ),
        CheckConstraint(
            "target_x >= 0 AND target_x <= 1 AND target_y >= 0 AND target_y <= 1 "
            "AND predicted_x >= 0 AND predicted_x <= 1 "
            "AND predicted_y >= 0 AND predicted_y <= 1",
            name="normalized_positions",
        ),
        CheckConstraint("error_normalized >= 0", name="nonnegative_error"),
        CheckConstraint(
            "tolerance_normalized > 0 AND tolerance_normalized <= 1",
            name="valid_tolerance",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    capture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    keyframe_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("keyframes.id", ondelete="CASCADE"), index=True
    )
    floor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("floors.id"), index=True)
    localization_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("processing_jobs.id"), index=True
    )
    target_x: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    target_y: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    predicted_x: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    predicted_y: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    error_normalized: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    tolerance_normalized: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    is_within_tolerance: Mapped[bool] = mapped_column(Boolean)
    created_by_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
