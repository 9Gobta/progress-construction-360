import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".insv"}
INSV_CONTENT_TYPES = {"application/octet-stream", "video/x-insta360"}


class MediaFileCreate(BaseModel):
    original_filename: str = Field(min_length=1, max_length=500)
    content_type: str = Field(min_length=1, max_length=150)
    size_bytes: int = Field(ge=1, le=10 * 1024 * 1024 * 1024)
    media_kind: str = "VIDEO"

    @field_validator("original_filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        filename = PurePath(value).name.strip()
        if not filename or filename != value.strip():
            raise ValueError("Filename must not contain a path")
        if PurePath(filename).suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
            raise ValueError("Only .mp4 and .insv files are supported")
        return filename

    @field_validator("media_kind")
    @classmethod
    def video_only_for_foundation(cls, value: str) -> str:
        if value.upper() != "VIDEO":
            raise ValueError("Only VIDEO media is supported by this endpoint")
        return "VIDEO"

    @field_validator("content_type")
    @classmethod
    def supported_video_type(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"video/mp4", *INSV_CONTENT_TYPES}:
            raise ValueError("Unsupported 360 video content type")
        return normalized


class MediaFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    media_kind: str
    bucket: str
    object_key: str
    original_filename: str | None
    content_type: str
    size_bytes: int
    checksum_sha256: str | None
    upload_status: str
    created_by_id: uuid.UUID | None
    created_at: datetime


class MultipartInitiateRead(BaseModel):
    media: MediaFileRead
    upload_session_id: uuid.UUID
    part_size_bytes: int
    part_count: int
    expires_at: datetime


class StorageStatusRead(BaseModel):
    provider: str
    project_object_bytes: int = Field(ge=0)
    disk_total_bytes: int | None = Field(default=None, ge=0)
    disk_free_bytes: int | None = Field(default=None, ge=0)
    minimum_free_bytes: int = Field(ge=0)
    upload_allowed: bool
    guard_path: str | None = None
    message: str


class MultipartPartRead(BaseModel):
    part_number: int
    etag: str
    size_bytes: int


class MultipartPartsRequest(BaseModel):
    part_numbers: list[int] = Field(min_length=1, max_length=50)

    @field_validator("part_numbers")
    @classmethod
    def valid_unique_parts(cls, value: list[int]) -> list[int]:
        if any(part < 1 or part > 10_000 for part in value):
            raise ValueError("Part number must be between 1 and 10000")
        if len(set(value)) != len(value):
            raise ValueError("Part numbers must be unique")
        return sorted(value)


class MultipartPartUrl(BaseModel):
    part_number: int
    url: str


class MultipartStatusRead(BaseModel):
    media_id: uuid.UUID
    original_filename: str | None
    size_bytes: int
    upload_session_id: uuid.UUID
    status: str
    part_size_bytes: int
    part_count: int
    expires_at: datetime
    uploaded_parts: list[MultipartPartRead]
    upload_urls: list[MultipartPartUrl] = Field(default_factory=list)


class CompletedPart(BaseModel):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=200)


class MultipartCompleteRequest(BaseModel):
    parts: list[CompletedPart] = Field(min_length=1, max_length=10_000)

    @field_validator("parts")
    @classmethod
    def ordered_unique_parts(cls, value: list[CompletedPart]) -> list[CompletedPart]:
        numbers = [part.part_number for part in value]
        if len(set(numbers)) != len(numbers):
            raise ValueError("Part numbers must be unique")
        return sorted(value, key=lambda part: part.part_number)


class MultipartCompleteRead(BaseModel):
    media: MediaFileRead
    capture_id: uuid.UUID
    capture_status: str
    processing_job_id: uuid.UUID


class CaptureCreate(BaseModel):
    source_video_id: uuid.UUID
    captured_at: datetime
    captured_by_text: str | None = Field(default=None, max_length=200)
    start_floor_id: uuid.UUID
    start_x: Decimal = Field(ge=0, le=1)
    start_y: Decimal = Field(ge=0, le=1)
    notes: str | None = Field(default=None, max_length=3000)
    dataset_split: Literal["DEVELOPMENT", "HOLDOUT_TEST"] = "DEVELOPMENT"

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value


class StitchedMediaAttach(BaseModel):
    media_id: uuid.UUID


class CaptureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    source_video_id: uuid.UUID
    captured_at: datetime
    captured_by_text: str | None
    start_floor_id: uuid.UUID
    start_x: Decimal
    start_y: Decimal
    notes: str | None
    dataset_split: Literal["DEVELOPMENT", "HOLDOUT_TEST"]
    status: str
    created_by_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ProcessingJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    capture_id: uuid.UUID
    job_type: str
    status: str
    progress_percent: Decimal
    attempt_no: int
    pipeline_version: str
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime


class VideoMetadataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    duration_ms: int
    width_px: int
    height_px: int
    fps: Decimal
    codec_name: str
    is_equirectangular: bool


class CameraPoseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    keyframe_id: uuid.UUID
    floor_id: uuid.UUID
    x: Decimal
    y: Decimal
    heading_deg: Decimal
    visual_x: Decimal | None
    visual_y: Decimal | None
    visual_heading_deg: Decimal | None
    visual_z: Decimal | None
    visual_ground_z: Decimal | None
    orientation_qx: Decimal | None
    orientation_qy: Decimal | None
    orientation_qz: Decimal | None
    orientation_qw: Decimal | None
    relative_z_m: Decimal | None
    confidence: Decimal
    localization_run_id: uuid.UUID
    algorithm: str
    needs_review: bool
    reviewed_by_id: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CameraPoseUpdate(BaseModel):
    floor_id: uuid.UUID
    x: Decimal = Field(ge=0, le=1)
    y: Decimal = Field(ge=0, le=1)
    heading_deg: Decimal = Field(ge=0, lt=360)


class CaptureStartPointUpdate(BaseModel):
    floor_id: uuid.UUID
    x: Decimal = Field(ge=0, le=1)
    y: Decimal = Field(ge=0, le=1)


class CaptureStartPointUpdateRead(BaseModel):
    floor_id: uuid.UUID
    x: Decimal
    y: Decimal
    path_point_count: int
    pose_count: int


class PathCalibrationAnchor(BaseModel):
    timestamp_ms: int = Field(ge=0)
    x: Decimal = Field(ge=0, le=1)
    y: Decimal = Field(ge=0, le=1)


class PathCalibrationRequest(BaseModel):
    floor_id: uuid.UUID
    anchors: list[PathCalibrationAnchor] = Field(min_length=2, max_length=2)


class PathCalibrationRead(BaseModel):
    path_point_count: int
    pose_count: int
    scale: float
    rotation_deg: float


class RigidPathTransformRequest(BaseModel):
    floor_id: uuid.UUID
    # `scale` remains accepted for older clients. New clients send independent
    # plan-axis scales so a monocular reconstruction can be stretched to the
    # drawing without moving individual camera points.
    scale: float | None = Field(default=None, gt=0, le=10)
    scale_x: float | None = Field(default=None, gt=0, le=10)
    scale_y: float | None = Field(default=None, gt=0, le=10)
    rotation_deg: float = Field(ge=-360, le=360)
    mirror: bool = False
    offset_x: float = Field(default=0, ge=-1, le=1)
    offset_y: float = Field(default=0, ge=-1, le=1)

    @model_validator(mode="after")
    def require_complete_scale(self) -> "RigidPathTransformRequest":
        if self.scale is None and (self.scale_x is None or self.scale_y is None):
            raise ValueError("Provide scale or both scale_x and scale_y")
        return self


class RigidPathTransformRead(BaseModel):
    path_point_count: int
    pose_count: int
    scale: float
    scale_x: float
    scale_y: float
    rotation_deg: float
    mirror: bool
    offset_x: float
    offset_y: float


class PathControlPointInput(BaseModel):
    keyframe_id: uuid.UUID
    x: Decimal = Field(ge=0, le=1)
    y: Decimal = Field(ge=0, le=1)


class PathControlPointFitRequest(BaseModel):
    floor_id: uuid.UUID
    control_points: list[PathControlPointInput] = Field(min_length=3, max_length=5)


class PathControlPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    capture_id: uuid.UUID
    keyframe_id: uuid.UUID
    floor_id: uuid.UUID
    x: Decimal
    y: Decimal
    error_normalized: Decimal
    created_by_id: uuid.UUID
    created_at: datetime


class PathControlPointFitRead(BaseModel):
    path_point_count: int
    pose_count: int
    scale: float
    rotation_deg: float
    mirror: bool
    offset_x: float
    offset_y: float
    rmse_normalized: float
    max_error_normalized: float
    control_points: list[PathControlPointRead]


class PathEvaluationPointInput(BaseModel):
    keyframe_id: uuid.UUID
    target_x: Decimal = Field(ge=0, le=1)
    target_y: Decimal = Field(ge=0, le=1)


class PathEvaluationRequest(BaseModel):
    floor_id: uuid.UUID
    tolerance_normalized: Decimal = Field(default=Decimal("0.03"), gt=0, le=1)
    evaluation_points: list[PathEvaluationPointInput] = Field(min_length=5, max_length=100)


class PathEvaluationPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    capture_id: uuid.UUID
    keyframe_id: uuid.UUID
    floor_id: uuid.UUID
    localization_run_id: uuid.UUID
    target_x: Decimal
    target_y: Decimal
    predicted_x: Decimal
    predicted_y: Decimal
    error_normalized: Decimal
    tolerance_normalized: Decimal
    is_within_tolerance: bool
    created_by_id: uuid.UUID
    created_at: datetime


class PathEvaluationSummary(BaseModel):
    point_count: int
    required_point_count: int = 20
    is_ready: bool
    tolerance_normalized: Decimal
    within_tolerance_count: int
    accuracy_percent: Decimal
    rmse_normalized: Decimal
    max_error_normalized: Decimal


class PathEvaluationRead(BaseModel):
    evaluation_points: list[PathEvaluationPointRead]
    summary: PathEvaluationSummary


class KeyframeRead(BaseModel):
    id: uuid.UUID
    frame_index: int
    timestamp_ms: int
    quality_status: str
    is_warp_point: bool
    image_url: str
    pose: CameraPoseRead | None = None


class RouteVectorRead(BaseModel):
    """A navigable spatial link between two extracted 360 images."""

    from_keyframe_id: uuid.UUID
    to_keyframe_id: uuid.UUID
    delta_x: float
    delta_y: float
    delta_z: float
    distance: float
    bearing_deg: float
    local_yaw_deg: float
    local_pitch_deg: float = 0.0
    direction_source: str
    confidence: float
    verified: bool
    verification_method: str


class CapturePathPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    floor_id: uuid.UUID
    timestamp_ms: int
    x: Decimal
    y: Decimal
    heading_deg: Decimal
    confidence: Decimal
    localization_run_id: uuid.UUID
    algorithm: str


class CaptureDetailRead(BaseModel):
    capture: CaptureRead
    metadata: VideoMetadataRead | None
    proxy_url: str | None
    keyframes: list[KeyframeRead]
    route_vectors: list[RouteVectorRead]
    path_points: list[CapturePathPointRead]
    control_points: list[PathControlPointRead]
    evaluation_points: list[PathEvaluationPointRead]
    evaluation_summary: PathEvaluationSummary | None
    jobs: list[ProcessingJobRead]


class LocalizationRunRead(BaseModel):
    job: ProcessingJobRead
    capture_status: str
