import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BEAM_STAGE_CODES = {"SETTING_OUT", "SHORING", "REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM"}
COLUMN_STAGE_CODES = {"REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM"}
STAIR_STAGE_CODES = {"SHORING", "REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM"}
SLAB_STAGE_CODES = {
    "STEP_1",
    "STEP_2",
    "STEP_3",
    "STEP_4",
    "STEP_5",
    "SHORING",
    "PLACE_PRECAST",
    "SOIL_COMPACTION",
    "REBAR",
    "FORMWORK",
    "CONCRETE",
    "STRIP_FORM",
}


class HumanProgressCreate(BaseModel):
    activity_id: uuid.UUID
    capture_id: uuid.UUID | None = None
    observed_at: datetime
    progress_percent: Decimal = Field(ge=0, le=100, decimal_places=3)
    note: str | None = Field(default=None, max_length=3000)

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class HumanProgressBulkCreate(BaseModel):
    entries: list[HumanProgressCreate] = Field(min_length=1, max_length=200)


class HumanProgressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    activity_id: uuid.UUID
    # Stable business key used to reconnect immutable observations when a new
    # schedule version creates new Activity UUIDs for the same WBS item.
    activity_wbs: str | None = None
    capture_id: uuid.UUID | None
    observed_at: datetime
    progress_percent: Decimal
    note: str | None
    entered_by_id: uuid.UUID
    created_at: datetime


class ProgressComparisonItem(BaseModel):
    activity_id: uuid.UUID
    wbs: str
    name: str
    planned_percent: Decimal
    human_actual_percent: Decimal | None
    human_observed_at: datetime | None
    variance_pp: Decimal | None


class ProgressComparisonRead(BaseModel):
    project_id: uuid.UUID
    capture_id: uuid.UUID
    capture_date: datetime
    schedule_version_id: uuid.UUID
    schedule_name: str
    items: list[ProgressComparisonItem]


class BeamStageRange(BaseModel):
    start_m: Decimal = Field(ge=0, decimal_places=3)
    end_m: Decimal = Field(gt=0, decimal_places=3)

    @model_validator(mode="after")
    def end_must_follow_start_m(self) -> "BeamStageRange":
        if self.end_m <= self.start_m:
            raise ValueError("end_m must be greater than start_m")
        return self


class BeamStageSummary(BaseModel):
    stage: str
    completed_length_m: Decimal
    total_length_m: Decimal
    progress_percent: Decimal


class BeamProgressValue(BaseModel):
    beam_segment_id: uuid.UUID
    progress_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=3)
    completed_stages: list[str] | None = None
    stage_ranges: dict[str, list[BeamStageRange]] | None = None
    evidence_keyframe_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("completed_stages")
    @classmethod
    def stages_must_be_known_and_unique(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(value) != len(set(value)) or not set(value).issubset(BEAM_STAGE_CODES):
            raise ValueError("completed_stages contains an unknown or duplicate stage")
        return value

    @field_validator("stage_ranges")
    @classmethod
    def range_stages_must_be_known(
        cls, value: dict[str, list[BeamStageRange]] | None
    ) -> dict[str, list[BeamStageRange]] | None:
        if value is not None and not set(value).issubset(BEAM_STAGE_CODES):
            raise ValueError("stage_ranges contains an unknown stage")
        return value


class BeamProgressBulkCreate(BaseModel):
    floor_id: uuid.UUID
    entries: list[BeamProgressValue] = Field(min_length=1, max_length=1000)


class BeamProgressAIRequest(BaseModel):
    floor_id: uuid.UUID


class BeamProgressItem(BaseModel):
    beam_segment_id: uuid.UUID
    code: str
    beam_type: str | None
    start_x: Decimal
    start_y: Decimal
    end_x: Decimal
    end_y: Decimal
    length_m: Decimal | None
    progress_percent: Decimal | None
    completed_stages: list[str] = Field(default_factory=list)
    stage_ranges: dict[str, list[BeamStageRange]] = Field(default_factory=dict)
    evidence_keyframe_id: uuid.UUID | None
    note: str | None
    entered_by_id: uuid.UUID | None
    created_at: datetime | None


class BeamProgressRead(BaseModel):
    project_id: uuid.UUID
    capture_id: uuid.UUID
    floor_id: uuid.UUID
    labeled_count: int
    segment_count: int
    weighted_progress_percent: Decimal | None
    total_length_m: Decimal
    completed_equivalent_length_m: Decimal
    stage_summaries: list[BeamStageSummary] = Field(default_factory=list)
    items: list[BeamProgressItem]


class ColumnProgressValue(BaseModel):
    structural_element_id: uuid.UUID
    completed_stages: list[str] = Field(default_factory=list)
    evidence_keyframe_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("completed_stages")
    @classmethod
    def stages_must_be_known_and_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or not set(value).issubset(COLUMN_STAGE_CODES):
            raise ValueError("completed_stages contains an unknown or duplicate stage")
        return value


class ColumnProgressBulkCreate(BaseModel):
    floor_id: uuid.UUID
    entries: list[ColumnProgressValue] = Field(min_length=1, max_length=200)


class ColumnProgressItem(BaseModel):
    structural_element_id: uuid.UUID
    code: str
    grid_label: str
    geometry_json: dict[str, object]
    progress_percent: Decimal | None
    completed_stages: list[str] = Field(default_factory=list)
    evidence_keyframe_id: uuid.UUID | None
    note: str | None
    entered_by_id: uuid.UUID | None
    created_at: datetime | None


class ColumnStageSummary(BaseModel):
    stage: str
    completed_count: int
    total_count: int
    progress_percent: Decimal


class ColumnProgressRead(BaseModel):
    project_id: uuid.UUID
    capture_id: uuid.UUID
    floor_id: uuid.UUID
    labeled_count: int
    column_count: int
    progress_percent: Decimal
    stage_summaries: list[ColumnStageSummary] = Field(default_factory=list)
    items: list[ColumnProgressItem]


class StairProgressValue(BaseModel):
    structural_element_id: uuid.UUID
    completed_stages: list[str] = Field(default_factory=list)
    evidence_keyframe_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("completed_stages")
    @classmethod
    def stages_must_be_known_and_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or not set(value).issubset(STAIR_STAGE_CODES):
            raise ValueError("completed_stages contains an unknown or duplicate stage")
        return value


class StairProgressBulkCreate(BaseModel):
    floor_id: uuid.UUID
    entries: list[StairProgressValue] = Field(min_length=1, max_length=200)


class StairProgressItem(BaseModel):
    structural_element_id: uuid.UUID
    code: str
    geometry_json: dict[str, object]
    progress_percent: Decimal | None
    completed_stages: list[str] = Field(default_factory=list)
    evidence_keyframe_id: uuid.UUID | None
    note: str | None
    entered_by_id: uuid.UUID | None
    created_at: datetime | None


class StairProgressRead(BaseModel):
    project_id: uuid.UUID
    capture_id: uuid.UUID
    floor_id: uuid.UUID
    labeled_count: int
    stair_count: int
    progress_percent: Decimal
    stage_summaries: list[ColumnStageSummary] = Field(default_factory=list)
    items: list[StairProgressItem]


class SlabProgressValue(BaseModel):
    structural_element_id: uuid.UUID
    completed_stages: list[str] = Field(default_factory=list)
    evidence_keyframe_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("completed_stages")
    @classmethod
    def stages_must_be_known_and_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or not set(value).issubset(SLAB_STAGE_CODES):
            raise ValueError("completed_stages contains an unknown or duplicate stage")
        return value


class SlabProgressBulkCreate(BaseModel):
    floor_id: uuid.UUID
    entries: list[SlabProgressValue] = Field(min_length=1, max_length=200)


class SlabProgressItem(BaseModel):
    structural_element_id: uuid.UUID
    code: str
    area_m2: Decimal
    geometry_json: dict[str, object]
    progress_percent: Decimal | None
    completed_stages: list[str] = Field(default_factory=list)
    evidence_keyframe_id: uuid.UUID | None
    note: str | None
    entered_by_id: uuid.UUID | None
    created_at: datetime | None


class SlabStageSummary(BaseModel):
    stage: str
    completed_area_m2: Decimal
    total_area_m2: Decimal
    progress_percent: Decimal


class SlabProgressRead(BaseModel):
    project_id: uuid.UUID
    capture_id: uuid.UUID
    floor_id: uuid.UUID
    labeled_count: int
    zone_count: int
    total_area_m2: Decimal
    progress_percent: Decimal
    stage_summaries: list[SlabStageSummary] = Field(default_factory=list)
    items: list[SlabProgressItem]


class RoofProgressValue(BaseModel):
    structural_element_id: uuid.UUID
    complete: bool | None = None
    completed_quantity: int | None = Field(default=None, ge=0, le=1000000)
    total_quantity: int | None = Field(default=None, gt=0, le=1000000)
    evidence_keyframe_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def completion_value_is_required(self) -> "RoofProgressValue":
        if self.complete is None and self.completed_quantity is None:
            raise ValueError("complete or completed_quantity is required")
        return self


class RoofProgressBulkCreate(BaseModel):
    floor_id: uuid.UUID
    entries: list[RoofProgressValue] = Field(min_length=1, max_length=200)


class RoofProgressBulkDelete(BaseModel):
    floor_id: uuid.UUID
    structural_element_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class RoofProgressItem(BaseModel):
    structural_element_id: uuid.UUID
    code: str
    activity_wbs: str
    geometry_json: dict[str, object]
    progress_percent: Decimal | None
    complete: bool
    completed_quantity: int | None = None
    total_quantity: int | None = None
    capture_id: uuid.UUID | None = None
    evidence_keyframe_id: uuid.UUID | None
    note: str | None
    entered_by_id: uuid.UUID | None
    created_at: datetime | None


class RoofProgressRead(BaseModel):
    project_id: uuid.UUID
    capture_id: uuid.UUID
    floor_id: uuid.UUID
    labeled_count: int
    element_count: int
    progress_percent: Decimal
    items: list[RoofProgressItem]


class BeamAICaptureEvaluation(BaseModel):
    capture_id: uuid.UUID
    captured_at: datetime
    segment_count: int
    human_actual_percent: Decimal
    ai_actual_percent: Decimal
    mae_pp: Decimal
    within_15_rate_percent: Decimal
    installed_f1: Decimal | None


class BeamAIEvaluationRead(BaseModel):
    project_id: uuid.UUID
    model_version: str
    capture_count: int
    segment_count: int
    mae_pp: Decimal | None
    within_15_rate_percent: Decimal | None
    installed_f1: Decimal | None
    passes_mae: bool
    passes_f1: bool
    captures: list[BeamAICaptureEvaluation]


class WorkProgressValue(BaseModel):
    work_item_id: uuid.UUID
    progress_percent: Decimal = Field(ge=0, le=100, decimal_places=3)
    evidence_keyframe_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)


class WorkProgressBulkCreate(BaseModel):
    floor_id: uuid.UUID
    entries: list[WorkProgressValue] = Field(min_length=1, max_length=200)


class WorkProgressAIRequest(BaseModel):
    floor_id: uuid.UUID


class WorkProgressItem(BaseModel):
    work_item_id: uuid.UUID
    code: str
    discipline: str
    name: str
    unit: str
    weight: Decimal
    sequence: int
    progress_percent: Decimal | None
    evidence_keyframe_id: uuid.UUID | None
    note: str | None


class WorkProgressRead(BaseModel):
    project_id: uuid.UUID
    capture_id: uuid.UUID
    floor_id: uuid.UUID
    labeled_count: int
    item_count: int
    human_progress_percent: Decimal | None
    items: list[WorkProgressItem]
