import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from progress_api.access import require_project_role
from progress_api.dependencies import CurrentUser, DbSession
from progress_api.models import (
    Activity,
    BeamProgressEntry,
    BeamProgressPrediction,
    BeamSegment,
    Capture,
    Floor,
    FloorWorkItem,
    HumanProgressEntry,
    Keyframe,
    ScheduleVersion,
    Sheet,
    StructuralElement,
    StructuralElementProgressEntry,
    WorkProgressEntry,
    WorkProgressPrediction,
)
from progress_api.schemas.progress import (
    BeamAICaptureEvaluation,
    BeamAIEvaluationRead,
    BeamProgressAIRequest,
    BeamProgressBulkCreate,
    BeamProgressItem,
    BeamProgressRead,
    BeamStageRange,
    BeamStageSummary,
    ColumnProgressBulkCreate,
    ColumnProgressItem,
    ColumnProgressRead,
    ColumnStageSummary,
    HumanProgressBulkCreate,
    HumanProgressCreate,
    HumanProgressRead,
    ProgressComparisonItem,
    ProgressComparisonRead,
    RoofProgressBulkCreate,
    RoofProgressBulkDelete,
    RoofProgressItem,
    RoofProgressRead,
    SlabProgressBulkCreate,
    SlabProgressItem,
    SlabProgressRead,
    SlabStageSummary,
    StairProgressBulkCreate,
    StairProgressItem,
    StairProgressRead,
    WorkProgressAIRequest,
    WorkProgressBulkCreate,
    WorkProgressItem,
    WorkProgressRead,
)
from progress_api.services.beam_progress_ai_v3 import (
    MODEL_VERSION,
    run_beam_progress_inference,
)
from progress_api.services.work_progress_ai import (
    MODEL_VERSION as WORK_MODEL_VERSION,
)
from progress_api.services.work_progress_ai import (
    run_work_progress_inference,
)

router = APIRouter()

FLOOR_ONE_BEAM_STAGES = ("SETTING_OUT", "REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM")
UPPER_FLOOR_BEAM_STAGES = ("SHORING", "REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM")
COLUMN_STAGES = ("REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM")
FLOOR_ONE_STAIR_STAGES = ("REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM")
UPPER_FLOOR_STAIR_STAGES = ("SHORING", "REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM")
LEGACY_SLAB_STAGES = ("STEP_1", "STEP_2", "STEP_3", "STEP_4", "STEP_5")
GS_SLAB_STAGES = ("SOIL_COMPACTION", "REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM")
FLOOR_ONE_S1_SLAB_STAGES = ("FORMWORK", "REBAR", "CONCRETE", "STRIP_FORM")
S1_SLAB_STAGES = ("SHORING", "REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM")
PC1_SLAB_STAGES = (
    "SHORING",
    "PLACE_PRECAST",
    "REBAR",
    "FORMWORK",
    "CONCRETE",
    "STRIP_FORM",
)
SLAB_STAGES = (*LEGACY_SLAB_STAGES, "SOIL_COMPACTION", *PC1_SLAB_STAGES)
ROOF_COMPLETE_STAGE = "COMPLETE"
COLUMN_GRID_X = (0.1998, 0.2893, 0.3791, 0.4689, 0.5586, 0.6484)
COLUMN_GRID_Y = (0.2729, 0.4072, 0.4711, 0.6056)
COLUMN_GRID_X_LABELS = ("1", "2", "3", "4", "5", "6")
COLUMN_GRID_Y_LABELS = ("A", "B", "C", "D")

DEFAULT_FLOOR_WORKS = (
    ("STR-01", "STRUCTURAL", "ฐานราก/ฐานเสาและตอม่อ"),
    ("STR-02", "STRUCTURAL", "เสาคอนกรีตเสริมเหล็ก"),
    ("STR-03", "STRUCTURAL", "คานคอนกรีตเสริมเหล็ก"),
    ("STR-04", "STRUCTURAL", "พื้นคอนกรีตเสริมเหล็ก"),
    ("STR-05", "STRUCTURAL", "บันไดและชานพัก"),
    ("STR-06", "STRUCTURAL", "ผนังโครงสร้าง/แกนลิฟต์"),
    ("ARC-01", "ARCHITECTURAL", "งานก่อผนัง"),
    ("ARC-02", "ARCHITECTURAL", "งานฉาบผนัง"),
    ("ARC-03", "ARCHITECTURAL", "งานฝ้าเพดาน"),
    ("ARC-04", "ARCHITECTURAL", "งานพื้นและวัสดุปูพื้น"),
    ("ARC-05", "ARCHITECTURAL", "งานผิวผนังและทาสี"),
    ("ARC-06", "ARCHITECTURAL", "ประตู หน้าต่าง และกระจก"),
    ("ARC-07", "ARCHITECTURAL", "ราวกันตกและงานโลหะ"),
    ("ARC-08", "ARCHITECTURAL", "งานสุขภัณฑ์และอุปกรณ์ติดตั้ง"),
    ("ARC-09", "ARCHITECTURAL", "งานภายนอกและส่วนประกอบอาคาร"),
)


def _ensure_floor_work_items(
    db: DbSession,
    project_id: uuid.UUID,
    floor_id: uuid.UUID,
) -> list[FloorWorkItem]:
    floor = db.get(Floor, floor_id)
    if floor is None or floor.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบชั้นอาคาร")
    existing = list(db.scalars(
        select(FloorWorkItem).where(
            FloorWorkItem.floor_id == floor_id, FloorWorkItem.is_active.is_(True)
        ).order_by(FloorWorkItem.sequence)
    ))
    if existing:
        # Revised thesis scope: progress is entered by people and covers
        # structural work only. Keep historical architectural rows in the
        # database, but never expose or aggregate them in the active workflow.
        return [item for item in existing if item.discipline == "STRUCTURAL"]
    structural_works = (
        row for row in DEFAULT_FLOOR_WORKS if row[1] == "STRUCTURAL"
    )
    for sequence, (code, discipline, name) in enumerate(structural_works, 1):
        db.add(FloorWorkItem(
            project_id=project_id, floor_id=floor_id, code=code,
            discipline=discipline, name=name, unit="percent",
            weight=Decimal("1"), sequence=sequence, is_active=True,
        ))
    db.commit()
    return list(db.scalars(
        select(FloorWorkItem).where(
            FloorWorkItem.floor_id == floor_id,
            FloorWorkItem.discipline == "STRUCTURAL",
        )
        .order_by(FloorWorkItem.sequence)
    ))


def _work_progress_result(
    project_id: uuid.UUID, capture_id: uuid.UUID, floor_id: uuid.UUID,
    items: list[FloorWorkItem], entries: list[WorkProgressEntry],
    _predictions: list[WorkProgressPrediction],
) -> WorkProgressRead:
    latest_entry: dict[uuid.UUID, WorkProgressEntry] = {}
    for row in entries:
        latest_entry.setdefault(row.work_item_id, row)
    human_weight = sum((item.weight for item in items if item.id in latest_entry), Decimal(0))
    human_total = sum(
        (
            latest_entry[item.id].progress_percent * item.weight
            for item in items
            if item.id in latest_entry
        ),
        Decimal(0),
    )
    result_items = []
    for item in items:
        human = latest_entry.get(item.id)
        result_items.append(WorkProgressItem(
            work_item_id=item.id, code=item.code, discipline=item.discipline,
            name=item.name, unit=item.unit, weight=item.weight, sequence=item.sequence,
            progress_percent=human.progress_percent if human else None,
            evidence_keyframe_id=human.evidence_keyframe_id if human else None,
            note=human.note if human else None,
        ))
    return WorkProgressRead(
        project_id=project_id, capture_id=capture_id, floor_id=floor_id,
        labeled_count=len(latest_entry), item_count=len(items),
        human_progress_percent=(
            (human_total / human_weight).quantize(Decimal("0.001"))
            if human_weight
            else None
        ),
        items=result_items,
    )


def _normalize_stage_ranges(
    stage_ranges: dict[str, list[BeamStageRange]],
    segment_length: Decimal,
    stages: tuple[str, ...],
) -> dict[str, list[dict[str, float]]]:
    normalized: dict[str, list[dict[str, float]]] = {}
    for stage in stages:
        raw_ranges = stage_ranges.get(stage, [])
        ordered = sorted(
            (
                (Decimal(str(item.start_m)), Decimal(str(item.end_m)))
                for item in raw_ranges
            ),
            key=lambda item: item[0],
        )
        merged: list[tuple[Decimal, Decimal]] = []
        for start_m, end_m in ordered:
            if start_m < 0 or end_m > segment_length or end_m <= start_m:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"ช่วงงาน {stage} ต้องอยู่ระหว่าง 0.000–"
                        f"{segment_length.quantize(Decimal('0.001'))} ม."
                    ),
                )
            if merged and start_m <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end_m))
            else:
                merged.append((start_m, end_m))
        if merged:
            normalized[stage] = [
                {"start_m": float(start_m), "end_m": float(end_m)}
                for start_m, end_m in merged
            ]
    return normalized


def _entry_stage_ranges(
    entry: BeamProgressEntry | None,
    segment_length: Decimal,
    stages: tuple[str, ...],
) -> dict[str, list[BeamStageRange]]:
    if entry is None:
        return {}
    if entry.stage_ranges_json is not None:
        result: dict[str, list[BeamStageRange]] = {}
        for stage in stages:
            ranges: list[BeamStageRange] = []
            for interval in entry.stage_ranges_json.get(stage, []):
                start_m = max(Decimal(0), min(segment_length, Decimal(str(interval["start_m"]))))
                end_m = max(Decimal(0), min(segment_length, Decimal(str(interval["end_m"]))))
                if end_m > start_m:
                    ranges.append(BeamStageRange(start_m=start_m, end_m=end_m))
            if ranges:
                result[stage] = ranges
        return result
    statuses = entry.stage_status_json or {
        stage: entry.progress_percent >= Decimal((index + 1) * 20)
        for index, stage in enumerate(stages)
    }
    return {
        stage: [BeamStageRange(start_m=Decimal(0), end_m=segment_length)]
        for stage in stages
        if statuses.get(stage, False) and segment_length > 0
    }


def _latest_stage_snapshots_per_capture(
    entries: list[BeamProgressEntry] | list[StructuralElementProgressEntry],
    *,
    element_id: uuid.UUID,
    element_id_attribute: str,
) -> list[BeamProgressEntry] | list[StructuralElementProgressEntry]:
    """Keep the newest edit per capture while retaining older capture stages.

    Entry queries are ordered by capture date descending and then edit time
    descending.  A second save on the same capture is therefore a correction,
    but a completed construction stage from an older capture must carry forward
    instead of disappearing when another stage is inspected later.
    """
    snapshots: list[BeamProgressEntry] | list[StructuralElementProgressEntry] = []
    seen_capture_ids: set[uuid.UUID] = set()
    for entry in entries:
        if getattr(entry, element_id_attribute) != element_id:
            continue
        if entry.capture_id in seen_capture_ids:
            continue
        seen_capture_ids.add(entry.capture_id)
        snapshots.append(entry)
    return snapshots


def _cumulative_stage_statuses(
    entries: list[StructuralElementProgressEntry],
    *,
    element_id: uuid.UUID,
) -> tuple[StructuralElementProgressEntry | None, dict[str, bool]]:
    snapshots = _latest_stage_snapshots_per_capture(
        entries,
        element_id=element_id,
        element_id_attribute="structural_element_id",
    )
    if not snapshots:
        return None, {}
    statuses: dict[str, bool] = {}
    for snapshot in snapshots:
        for stage, complete in (snapshot.stage_status_json or {}).items():
            if complete:
                statuses[stage] = True
    return snapshots[0], statuses


def _cumulative_beam_stage_ranges(
    entries: list[BeamProgressEntry],
    *,
    segment_id: uuid.UUID,
    segment_length: Decimal,
    stages: tuple[str, ...],
) -> tuple[BeamProgressEntry | None, dict[str, list[BeamStageRange]]]:
    snapshots = _latest_stage_snapshots_per_capture(
        entries,
        element_id=segment_id,
        element_id_attribute="beam_segment_id",
    )
    if not snapshots:
        return None, {}
    combined: dict[str, list[BeamStageRange]] = {}
    for snapshot in snapshots:
        for stage, ranges in _entry_stage_ranges(snapshot, segment_length, stages).items():
            combined.setdefault(stage, []).extend(ranges)
    normalized = _normalize_stage_ranges(combined, segment_length, stages)
    return snapshots[0], {
        stage: [BeamStageRange(**interval) for interval in ranges]
        for stage, ranges in normalized.items()
    }


def _load_work_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
):
    capture = db.get(Capture, capture_id)
    if capture is None or capture.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบ Capture")
    items = _ensure_floor_work_items(db, project_id, floor_id)
    item_ids = [item.id for item in items]
    entries = list(db.scalars(
        select(WorkProgressEntry)
        .join(Capture, WorkProgressEntry.capture_id == Capture.id)
        .where(
            WorkProgressEntry.project_id == project_id,
            WorkProgressEntry.work_item_id.in_(item_ids),
            Capture.captured_at <= capture.captured_at,
        )
        .order_by(Capture.captured_at.desc(), WorkProgressEntry.created_at.desc())
    ))
    predictions = list(db.scalars(select(WorkProgressPrediction).where(
        WorkProgressPrediction.capture_id == capture_id,
        WorkProgressPrediction.work_item_id.in_(item_ids),
    ).order_by(WorkProgressPrediction.created_at.desc())))
    return capture, items, entries, predictions


def _beam_progress_result(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    segments: list[BeamSegment],
    entries: list[BeamProgressEntry],
    _predictions: list[BeamProgressPrediction],
    stages: tuple[str, ...] = FLOOR_ONE_BEAM_STAGES,
) -> BeamProgressRead:
    weighted_sum = Decimal(0)
    total_weight = Decimal(0)
    stage_completed_lengths = {stage: Decimal(0) for stage in stages}
    items: list[BeamProgressItem] = []
    labeled_count = 0
    for segment in segments:
        weight = segment.length_m or Decimal(1)
        total_weight += weight
        entry, stage_ranges = _cumulative_beam_stage_ranges(
            entries,
            segment_id=segment.id,
            segment_length=weight,
            stages=stages,
        )
        if entry is not None:
            labeled_count += 1
        completed_equivalent = sum(
            (
                item.end_m - item.start_m
                for ranges in stage_ranges.values()
                for item in ranges
            ),
            Decimal(0),
        )
        item_progress = None
        if entry is not None:
            item_progress = (
                completed_equivalent / (weight * Decimal(len(stages))) * Decimal(100)
            ).quantize(Decimal("0.001")) if (
                weight > 0
                and (entry.stage_ranges_json is not None or entry.stage_status_json is not None)
            ) else entry.progress_percent
        if item_progress is not None:
            weighted_sum += item_progress * weight
        for stage, ranges in stage_ranges.items():
            stage_completed_lengths[stage] += sum(
                (item.end_m - item.start_m for item in ranges), Decimal(0)
            )
        items.append(
            BeamProgressItem(
                beam_segment_id=segment.id,
                code=segment.code,
                beam_type=segment.beam_type,
                start_x=segment.start_x,
                start_y=segment.start_y,
                end_x=segment.end_x,
                end_y=segment.end_y,
                length_m=segment.length_m,
                progress_percent=item_progress,
                completed_stages=[
                    stage
                    for stage in stages
                    if sum(
                        (item.end_m - item.start_m for item in stage_ranges.get(stage, [])),
                        Decimal(0),
                    ) >= weight - Decimal("0.001")
                ],
                stage_ranges=stage_ranges,
                evidence_keyframe_id=entry.evidence_keyframe_id if entry else None,
                note=entry.note if entry else None,
                entered_by_id=entry.entered_by_id if entry else None,
                created_at=entry.created_at if entry else None,
            )
        )
    return BeamProgressRead(
        project_id=project_id,
        capture_id=capture_id,
        floor_id=floor_id,
        labeled_count=labeled_count,
        segment_count=len(segments),
        weighted_progress_percent=(weighted_sum / total_weight).quantize(Decimal("0.001"))
        if total_weight
        else None,
        total_length_m=sum((segment.length_m or Decimal(0) for segment in segments), Decimal(0)),
        completed_equivalent_length_m=(weighted_sum / Decimal(100)).quantize(Decimal("0.001")),
        stage_summaries=[
            BeamStageSummary(
                stage=stage,
                completed_length_m=completed.quantize(Decimal("0.001")),
                total_length_m=total_weight.quantize(Decimal("0.001")),
                progress_percent=(completed / total_weight * Decimal(100)).quantize(
                    Decimal("0.001")
                )
                if total_weight
                else Decimal(0),
            )
            for stage, completed in stage_completed_lengths.items()
        ],
        items=items,
    )


def _beam_stages_for_floor(db: DbSession, floor_id: uuid.UUID) -> tuple[str, ...]:
    floor = db.get(Floor, floor_id)
    return UPPER_FLOOR_BEAM_STAGES if floor and floor.level_index >= 2 else FLOOR_ONE_BEAM_STAGES


def _load_beam_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
) -> tuple[
    Capture,
    list[BeamSegment],
    list[BeamProgressEntry],
    list[BeamProgressPrediction],
]:
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="ไม่พบ Capture หรือชั้นอาคาร")
    segments = list(
        db.scalars(
            select(BeamSegment)
            .join(Sheet, BeamSegment.sheet_id == Sheet.id)
            .where(Sheet.floor_id == floor_id, BeamSegment.is_active.is_(True))
            .order_by(BeamSegment.code)
        )
    )
    entries = list(
        db.scalars(
            select(BeamProgressEntry)
            .join(Capture, BeamProgressEntry.capture_id == Capture.id)
            .where(
                BeamProgressEntry.project_id == project_id,
                BeamProgressEntry.beam_segment_id.in_([item.id for item in segments]),
                Capture.captured_at <= capture.captured_at,
            )
            .order_by(Capture.captured_at.desc(), BeamProgressEntry.created_at.desc())
        )
    ) if segments else []
    predictions = list(
        db.scalars(
            select(BeamProgressPrediction)
            .where(
                BeamProgressPrediction.project_id == project_id,
                BeamProgressPrediction.capture_id == capture_id,
                BeamProgressPrediction.beam_segment_id.in_([item.id for item in segments]),
            )
            .order_by(BeamProgressPrediction.created_at.desc())
        )
    ) if segments else []
    return capture, segments, entries, predictions


def _column_center(element: StructuralElement) -> tuple[float, float]:
    footprint = element.geometry_json.get("footprint", [])
    if not isinstance(footprint, list) or not footprint:
        return 0.0, 0.0
    points = [point for point in footprint if isinstance(point, list) and len(point) >= 2]
    if not points:
        return 0.0, 0.0
    return (
        sum(float(point[0]) for point in points) / len(points),
        sum(float(point[1]) for point in points) / len(points),
    )


def _column_grid_label(element: StructuralElement) -> str:
    x, y = _column_center(element)
    x_index = min(range(len(COLUMN_GRID_X)), key=lambda index: abs(COLUMN_GRID_X[index] - x))
    y_index = min(range(len(COLUMN_GRID_Y)), key=lambda index: abs(COLUMN_GRID_Y[index] - y))
    return f"{COLUMN_GRID_Y_LABELS[y_index]}/{COLUMN_GRID_X_LABELS[x_index]}"


def _load_column_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
) -> tuple[Capture, list[StructuralElement], list[StructuralElementProgressEntry]]:
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="ไม่พบ Capture หรือชั้นอาคาร")
    columns = list(
        db.scalars(
            select(StructuralElement).where(
                StructuralElement.project_id == project_id,
                StructuralElement.floor_id == floor_id,
                StructuralElement.element_kind == "COLUMN",
                StructuralElement.is_active.is_(True),
            )
        )
    )
    columns.sort(key=lambda item: (_column_center(item)[1], _column_center(item)[0]))
    column_ids = [item.id for item in columns]
    entries = list(
        db.scalars(
            select(StructuralElementProgressEntry)
            .join(Capture, StructuralElementProgressEntry.capture_id == Capture.id)
            .where(
                StructuralElementProgressEntry.project_id == project_id,
                StructuralElementProgressEntry.structural_element_id.in_(column_ids),
                Capture.captured_at <= capture.captured_at,
            )
            .order_by(
                Capture.captured_at.desc(),
                StructuralElementProgressEntry.created_at.desc(),
            )
        )
    ) if column_ids else []
    return capture, columns, entries


def _column_progress_result(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    columns: list[StructuralElement],
    entries: list[StructuralElementProgressEntry],
) -> ColumnProgressRead:
    latest: dict[uuid.UUID, StructuralElementProgressEntry] = {}
    for entry in entries:
        latest.setdefault(entry.structural_element_id, entry)
    completed_counts = {stage: 0 for stage in COLUMN_STAGES}
    items: list[ColumnProgressItem] = []
    total_completed_stages = 0
    for column in columns:
        entry = latest.get(column.id)
        statuses = entry.stage_status_json if entry else {}
        completed_stages = [stage for stage in COLUMN_STAGES if statuses.get(stage, False)]
        total_completed_stages += len(completed_stages)
        for stage in completed_stages:
            completed_counts[stage] += 1
        items.append(
            ColumnProgressItem(
                structural_element_id=column.id,
                code=column.code.split(" · ", 1)[0],
                grid_label=_column_grid_label(column),
                geometry_json=column.geometry_json,
                progress_percent=entry.progress_percent if entry else None,
                completed_stages=completed_stages,
                evidence_keyframe_id=entry.evidence_keyframe_id if entry else None,
                note=entry.note if entry else None,
                entered_by_id=entry.entered_by_id if entry else None,
                created_at=entry.created_at if entry else None,
            )
        )
    denominator = len(columns) * len(COLUMN_STAGES)
    progress_percent = (
        Decimal(total_completed_stages) / Decimal(denominator) * Decimal(100)
    ).quantize(Decimal("0.001")) if denominator else Decimal(0)
    return ColumnProgressRead(
        project_id=project_id,
        capture_id=capture_id,
        floor_id=floor_id,
        labeled_count=len(latest),
        column_count=len(columns),
        progress_percent=progress_percent,
        stage_summaries=[
            ColumnStageSummary(
                stage=stage,
                completed_count=completed_counts[stage],
                total_count=len(columns),
                progress_percent=(
                    Decimal(completed_counts[stage]) / Decimal(len(columns)) * Decimal(100)
                ).quantize(Decimal("0.001")) if columns else Decimal(0),
            )
            for stage in COLUMN_STAGES
        ],
        items=items,
    )


def _stair_stages_for_floor(db: DbSession, floor_id: uuid.UUID) -> tuple[str, ...]:
    floor = db.get(Floor, floor_id)
    return UPPER_FLOOR_STAIR_STAGES if floor and floor.level_index >= 2 else FLOOR_ONE_STAIR_STAGES


def _load_stair_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
) -> tuple[Capture, list[StructuralElement], list[StructuralElementProgressEntry]]:
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="ไม่พบ Capture หรือชั้นอาคาร")
    stairs = list(db.scalars(select(StructuralElement).where(
        StructuralElement.project_id == project_id,
        StructuralElement.floor_id == floor_id,
        StructuralElement.element_kind == "STAIR",
        StructuralElement.is_active.is_(True),
    )))
    stairs.sort(key=lambda item: (_column_center(item)[1], _column_center(item)[0], item.code))
    stair_ids = [item.id for item in stairs]
    entries = list(db.scalars(
        select(StructuralElementProgressEntry)
        .join(Capture, StructuralElementProgressEntry.capture_id == Capture.id)
        .where(
            StructuralElementProgressEntry.project_id == project_id,
            StructuralElementProgressEntry.structural_element_id.in_(stair_ids),
            Capture.captured_at <= capture.captured_at,
        )
        .order_by(Capture.captured_at.desc(), StructuralElementProgressEntry.created_at.desc())
    )) if stair_ids else []
    return capture, stairs, entries


def _stair_progress_result(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    stairs: list[StructuralElement],
    entries: list[StructuralElementProgressEntry],
    stages: tuple[str, ...],
) -> StairProgressRead:
    completed_counts = {stage: 0 for stage in stages}
    items: list[StairProgressItem] = []
    labeled_count = 0
    for stair in stairs:
        entry, statuses = _cumulative_stage_statuses(entries, element_id=stair.id)
        if entry is not None:
            labeled_count += 1
        completed_stages = [stage for stage in stages if statuses.get(stage, False)]
        for stage in completed_stages:
            completed_counts[stage] += 1
        items.append(StairProgressItem(
            structural_element_id=stair.id,
            code=stair.code,
            geometry_json=stair.geometry_json,
            progress_percent=(
                Decimal(len(completed_stages)) / Decimal(len(stages)) * Decimal(100)
            ).quantize(Decimal("0.001")) if entry else None,
            completed_stages=completed_stages,
            evidence_keyframe_id=entry.evidence_keyframe_id if entry else None,
            note=entry.note if entry else None,
            entered_by_id=entry.entered_by_id if entry else None,
            created_at=entry.created_at if entry else None,
        ))
    denominator = len(stairs) * len(stages)
    completed_total = sum(completed_counts.values())
    return StairProgressRead(
        project_id=project_id,
        capture_id=capture_id,
        floor_id=floor_id,
        labeled_count=labeled_count,
        stair_count=len(stairs),
        progress_percent=(
            Decimal(completed_total) / Decimal(denominator) * Decimal(100)
        ).quantize(Decimal("0.001")) if denominator else Decimal(0),
        stage_summaries=[ColumnStageSummary(
            stage=stage,
            completed_count=completed_counts[stage],
            total_count=len(stairs),
            progress_percent=(
                Decimal(completed_counts[stage]) / Decimal(len(stairs)) * Decimal(100)
            ).quantize(Decimal("0.001")) if stairs else Decimal(0),
        ) for stage in stages],
        items=items,
    )


def _slab_area_m2(element: StructuralElement) -> Decimal:
    documented_area = element.geometry_json.get("area_m2")
    if documented_area is not None:
        return Decimal(str(documented_area)).quantize(Decimal("0.001"))
    footprint = element.geometry_json.get("footprint", [])
    if not isinstance(footprint, list) or len(footprint) < 3:
        return Decimal(0)
    points = [(Decimal(str(point[0])), Decimal(str(point[1]))) for point in footprint]
    normalized_area = abs(sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1], strict=True)
    )) / Decimal(2)
    x_scale = Decimal("18.75") / Decimal(str(COLUMN_GRID_X[-1] - COLUMN_GRID_X[0]))
    y_scale = Decimal("9.90") / Decimal(str(COLUMN_GRID_Y[-1] - COLUMN_GRID_Y[0]))
    return (normalized_area * x_scale * y_scale).quantize(Decimal("0.001"))


def _slab_type(element: StructuralElement) -> str:
    value = str(element.geometry_json.get("slab_type") or "LEGACY").upper()
    return value if value in {"GS", "S1", "PC1"} else "LEGACY"


def _slab_stage_codes(element: StructuralElement) -> tuple[str, ...]:
    slab_type = _slab_type(element)
    workflow = str(element.geometry_json.get("slab_workflow") or "").upper()
    if slab_type == "GS":
        return GS_SLAB_STAGES
    if slab_type == "PC1":
        return PC1_SLAB_STAGES
    if slab_type == "S1" and workflow == "S1_FLOOR_1":
        return FLOOR_ONE_S1_SLAB_STAGES
    if slab_type == "S1":
        return S1_SLAB_STAGES
    return LEGACY_SLAB_STAGES


def _normalized_slab_stages(
    element: StructuralElement,
    statuses: dict[str, object],
) -> list[str]:
    required = _slab_stage_codes(element)
    if any(statuses.get(stage, False) for stage in required):
        return [stage for stage in required if statuses.get(stage, False)]
    # Existing records used ordinal STEP_1..STEP_5 values. Interpret those
    # values through the reviewed type-specific workflow without rewriting the
    # historical inspection entries.
    return [
        required[index]
        for index, legacy_stage in enumerate(LEGACY_SLAB_STAGES)
        if index < len(required) and statuses.get(legacy_stage, False)
    ]


def _load_slab_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
) -> tuple[Capture, list[StructuralElement], list[StructuralElementProgressEntry]]:
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="ไม่พบ Capture หรือชั้นอาคาร")
    slabs = list(db.scalars(select(StructuralElement).where(
        StructuralElement.project_id == project_id,
        StructuralElement.floor_id == floor_id,
        StructuralElement.element_kind == "SLAB",
        StructuralElement.is_active.is_(True),
    )))
    slabs.sort(key=lambda item: (_column_center(item)[1], _column_center(item)[0]))
    slab_ids = [item.id for item in slabs]
    entries = list(db.scalars(
        select(StructuralElementProgressEntry)
        .join(Capture, StructuralElementProgressEntry.capture_id == Capture.id)
        .where(
            StructuralElementProgressEntry.project_id == project_id,
            StructuralElementProgressEntry.structural_element_id.in_(slab_ids),
            Capture.captured_at <= capture.captured_at,
        )
        .order_by(Capture.captured_at.desc(), StructuralElementProgressEntry.created_at.desc())
    )) if slab_ids else []
    return capture, slabs, entries


def _slab_progress_result(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    slabs: list[StructuralElement],
    entries: list[StructuralElementProgressEntry],
) -> SlabProgressRead:
    total_area = sum((_slab_area_m2(item) for item in slabs), Decimal(0))
    completed_area = {stage: Decimal(0) for stage in SLAB_STAGES}
    eligible_area = {stage: Decimal(0) for stage in SLAB_STAGES}
    items: list[SlabProgressItem] = []
    denominator = Decimal(0)
    labeled_count = 0
    for slab in slabs:
        entry, statuses = _cumulative_stage_statuses(entries, element_id=slab.id)
        if entry is not None:
            labeled_count += 1
        required_stages = _slab_stage_codes(slab)
        stages = _normalized_slab_stages(slab, statuses)
        area = _slab_area_m2(slab)
        denominator += area * Decimal(len(required_stages))
        for stage in required_stages:
            eligible_area[stage] += area
        for stage in stages:
            completed_area[stage] += area
        items.append(SlabProgressItem(
            structural_element_id=slab.id,
            code=slab.code,
            area_m2=area,
            geometry_json=slab.geometry_json,
            progress_percent=(
                Decimal(len(stages)) / Decimal(len(required_stages)) * Decimal(100)
            ).quantize(Decimal("0.001")) if entry else None,
            completed_stages=stages,
            evidence_keyframe_id=entry.evidence_keyframe_id if entry else None,
            note=entry.note if entry else None,
            entered_by_id=entry.entered_by_id if entry else None,
            created_at=entry.created_at if entry else None,
        ))
    completed_equivalent_area = sum(completed_area.values(), Decimal(0))
    progress = (completed_equivalent_area / denominator * Decimal(100)).quantize(
        Decimal("0.001")
    ) if denominator else Decimal(0)
    return SlabProgressRead(
        project_id=project_id,
        capture_id=capture_id,
        floor_id=floor_id,
        labeled_count=labeled_count,
        zone_count=len(slabs),
        total_area_m2=total_area.quantize(Decimal("0.001")),
        progress_percent=progress,
        stage_summaries=[SlabStageSummary(
            stage=stage,
            completed_area_m2=completed_area[stage].quantize(Decimal("0.001")),
            total_area_m2=eligible_area[stage].quantize(Decimal("0.001")),
            progress_percent=(completed_area[stage] / eligible_area[stage] * Decimal(100)).quantize(
                Decimal("0.001")
            ) if eligible_area[stage] else Decimal(0),
        ) for stage in SLAB_STAGES if eligible_area[stage]],
        items=items,
    )


def _load_roof_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
) -> tuple[Capture, list[StructuralElement], list[StructuralElementProgressEntry]]:
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="ไม่พบ Capture หรือชั้นหลังคา")
    roofs = list(db.scalars(select(StructuralElement).where(
        StructuralElement.project_id == project_id,
        StructuralElement.floor_id == floor_id,
        StructuralElement.element_kind == "ROOF",
        StructuralElement.is_active.is_(True),
    )))
    roofs.sort(key=lambda item: (
        str(item.geometry_json.get("activity_wbs", "")),
        _column_center(item)[1],
        _column_center(item)[0],
        item.code,
    ))
    roof_ids = [item.id for item in roofs]
    entries = list(db.scalars(
        select(StructuralElementProgressEntry)
        .join(Capture, StructuralElementProgressEntry.capture_id == Capture.id)
        .where(
            StructuralElementProgressEntry.project_id == project_id,
            StructuralElementProgressEntry.structural_element_id.in_(roof_ids),
            Capture.captured_at <= capture.captured_at,
        )
        .order_by(Capture.captured_at.desc(), StructuralElementProgressEntry.created_at.desc())
    )) if roof_ids else []
    return capture, roofs, entries


def _roof_total_quantity(roof: StructuralElement) -> int:
    if str(roof.geometry_json.get("progress_mode", "")).upper() != "COUNT":
        return 1
    try:
        return max(1, int(roof.geometry_json.get("total_quantity", 1)))
    except (TypeError, ValueError):
        return 1


def _roof_completed_quantity(
    entry: StructuralElementProgressEntry | None,
    total_quantity: int,
) -> int:
    if entry is None:
        return 0
    raw_quantity = entry.stage_status_json.get("completed_quantity")
    if raw_quantity is not None and not isinstance(raw_quantity, bool):
        try:
            return max(0, min(total_quantity, int(raw_quantity)))
        except (TypeError, ValueError):
            pass
    if (
        entry.stage_status_json.get(ROOF_COMPLETE_STAGE, False)
        or entry.progress_percent >= Decimal(100)
    ):
        return total_quantity
    return max(0, min(
        total_quantity,
        int((entry.progress_percent / Decimal(100) * total_quantity).quantize(Decimal("1"))),
    ))


def _roof_progress_result(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    roofs: list[StructuralElement],
    entries: list[StructuralElementProgressEntry],
) -> RoofProgressRead:
    latest: dict[uuid.UUID, StructuralElementProgressEntry] = {}
    for entry in entries:
        latest.setdefault(entry.structural_element_id, entry)
    completed_quantity_sum = 0
    total_quantity_sum = 0
    items: list[RoofProgressItem] = []
    for roof in roofs:
        entry = latest.get(roof.id)
        total_quantity = _roof_total_quantity(roof)
        completed_quantity = _roof_completed_quantity(entry, total_quantity)
        complete = completed_quantity >= total_quantity
        completed_quantity_sum += completed_quantity
        total_quantity_sum += total_quantity
        count_mode = str(roof.geometry_json.get("progress_mode", "")).upper() == "COUNT"
        items.append(RoofProgressItem(
            structural_element_id=roof.id,
            code=roof.code,
            activity_wbs=str(roof.geometry_json.get("activity_wbs", "")),
            geometry_json=roof.geometry_json,
            progress_percent=(
                Decimal(completed_quantity) / Decimal(total_quantity) * Decimal(100)
            ).quantize(Decimal("0.001")) if entry else None,
            complete=complete,
            completed_quantity=completed_quantity if count_mode else None,
            total_quantity=total_quantity if count_mode else None,
            capture_id=entry.capture_id if entry else None,
            evidence_keyframe_id=entry.evidence_keyframe_id if entry else None,
            note=entry.note if entry else None,
            entered_by_id=entry.entered_by_id if entry else None,
            created_at=entry.created_at if entry else None,
        ))
    progress = (
        Decimal(completed_quantity_sum) / Decimal(total_quantity_sum) * Decimal(100)
    ).quantize(Decimal("0.001")) if total_quantity_sum else Decimal(0)
    return RoofProgressRead(
        project_id=project_id,
        capture_id=capture_id,
        floor_id=floor_id,
        labeled_count=len(latest),
        element_count=len(roofs),
        progress_percent=progress,
        items=items,
    )


@router.get(
    "/{project_id}/captures/{capture_id}/beam-progress",
    response_model=BeamProgressRead,
)
def get_beam_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> BeamProgressRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    _capture, segments, entries, predictions = _load_beam_progress(
        project_id, capture_id, floor_id, db
    )
    return _beam_progress_result(
        project_id, capture_id, floor_id, segments, entries, predictions,
        _beam_stages_for_floor(db, floor_id),
    )


@router.put(
    "/{project_id}/captures/{capture_id}/beam-progress",
    response_model=BeamProgressRead,
)
def save_beam_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: BeamProgressBulkCreate,
    db: DbSession,
    user: CurrentUser,
) -> BeamProgressRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "sub_admin", "reviewer"}
    )
    capture, segments, _entries, _predictions = _load_beam_progress(
        project_id, capture_id, payload.floor_id, db
    )
    beam_stages = _beam_stages_for_floor(db, payload.floor_id)
    segment_ids = {segment.id for segment in segments}
    requested_ids = [entry.beam_segment_id for entry in payload.entries]
    invalid_segments = (
        len(set(requested_ids)) != len(requested_ids)
        or not set(requested_ids).issubset(segment_ids)
    )
    if invalid_segments:
        raise HTTPException(status_code=422, detail="รายการคานไม่ถูกต้องหรือมีรหัสซ้ำ")
    keyframe_ids = {
        entry.evidence_keyframe_id
        for entry in payload.entries
        if entry.evidence_keyframe_id is not None
    }
    valid_keyframes = set(
        db.scalars(
            select(Keyframe.id).where(
                Keyframe.capture_id == capture.id, Keyframe.id.in_(keyframe_ids)
            )
        )
    ) if keyframe_ids else set()
    if valid_keyframes != keyframe_ids:
        raise HTTPException(status_code=422, detail="ภาพหลักฐานไม่ได้อยู่ใน Capture นี้")
    for item in payload.entries:
        if (
            item.completed_stages is None
            and item.progress_percent is None
            and item.stage_ranges is None
        ):
            raise HTTPException(
                status_code=422,
                detail="ต้องระบุ progress_percent, completed_stages หรือ stage_ranges",
            )
        segment = next(segment for segment in segments if segment.id == item.beam_segment_id)
        segment_length = segment.length_m or Decimal(0)
        stage_ranges_json = None
        completed_stages = item.completed_stages
        if item.stage_ranges is not None:
            if segment_length <= 0:
                raise HTTPException(status_code=422, detail="คานที่เลือกไม่มีความยาวอ้างอิง")
            stage_ranges_json = _normalize_stage_ranges(
                item.stage_ranges,
                segment_length,
                beam_stages,
            )
            covered = sum(
                (
                    Decimal(str(interval["end_m"])) - Decimal(str(interval["start_m"]))
                    for ranges in stage_ranges_json.values()
                    for interval in ranges
                ),
                Decimal(0),
            )
            progress_percent = (
                covered / (segment_length * Decimal(len(beam_stages))) * Decimal(100)
            ).quantize(Decimal("0.001"))
            completed_stages = [
                stage
                for stage, ranges in stage_ranges_json.items()
                if sum(
                    (
                        Decimal(str(interval["end_m"]))
                        - Decimal(str(interval["start_m"]))
                        for interval in ranges
                    ),
                    Decimal(0),
                )
                >= segment_length - Decimal("0.001")
            ]
        else:
            progress_percent = (
                Decimal(len(completed_stages)) / Decimal(len(beam_stages)) * Decimal(100)
                if completed_stages is not None
                else item.progress_percent
            )
        db.add(
            BeamProgressEntry(
                project_id=project_id,
                capture_id=capture_id,
                beam_segment_id=item.beam_segment_id,
                evidence_keyframe_id=item.evidence_keyframe_id,
                progress_percent=progress_percent,
                stage_status_json={
                    stage: stage in completed_stages
                    for stage in beam_stages
                } if completed_stages is not None else None,
                stage_ranges_json=stage_ranges_json,
                note=(item.note or "").strip() or None,
                entered_by_id=user.id,
            )
        )
    db.commit()
    _capture, segments, entries, predictions = _load_beam_progress(
        project_id, capture_id, payload.floor_id, db
    )
    return _beam_progress_result(
        project_id, capture_id, payload.floor_id, segments, entries, predictions,
        beam_stages,
    )


@router.get(
    "/{project_id}/captures/{capture_id}/column-progress",
    response_model=ColumnProgressRead,
)
def get_column_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> ColumnProgressRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    _capture, columns, entries = _load_column_progress(
        project_id, capture_id, floor_id, db
    )
    return _column_progress_result(project_id, capture_id, floor_id, columns, entries)


@router.put(
    "/{project_id}/captures/{capture_id}/column-progress",
    response_model=ColumnProgressRead,
)
def save_column_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: ColumnProgressBulkCreate,
    db: DbSession,
    user: CurrentUser,
) -> ColumnProgressRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "sub_admin", "reviewer"}
    )
    capture, columns, _entries = _load_column_progress(
        project_id, capture_id, payload.floor_id, db
    )
    column_ids = {column.id for column in columns}
    requested_ids = [entry.structural_element_id for entry in payload.entries]
    if len(set(requested_ids)) != len(requested_ids) or not set(requested_ids).issubset(column_ids):
        raise HTTPException(status_code=422, detail="รายการเสาไม่ถูกต้องหรือมีรหัสซ้ำ")
    keyframe_ids = {
        entry.evidence_keyframe_id
        for entry in payload.entries
        if entry.evidence_keyframe_id is not None
    }
    valid_keyframes = set(
        db.scalars(
            select(Keyframe.id).where(
                Keyframe.capture_id == capture.id,
                Keyframe.id.in_(keyframe_ids),
            )
        )
    ) if keyframe_ids else set()
    if valid_keyframes != keyframe_ids:
        raise HTTPException(status_code=422, detail="ภาพหลักฐานไม่ได้อยู่ใน Capture นี้")
    for item in payload.entries:
        statuses = {stage: stage in item.completed_stages for stage in COLUMN_STAGES}
        db.add(
            StructuralElementProgressEntry(
                project_id=project_id,
                capture_id=capture_id,
                structural_element_id=item.structural_element_id,
                evidence_keyframe_id=item.evidence_keyframe_id,
                progress_percent=Decimal(len(item.completed_stages) * 25),
                stage_status_json=statuses,
                note=(item.note or "").strip() or None,
                entered_by_id=user.id,
            )
        )
    db.commit()
    _capture, columns, entries = _load_column_progress(
        project_id, capture_id, payload.floor_id, db
    )
    return _column_progress_result(project_id, capture_id, payload.floor_id, columns, entries)


@router.get(
    "/{project_id}/captures/{capture_id}/stair-progress",
    response_model=StairProgressRead,
)
def get_stair_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> StairProgressRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    _capture, stairs, entries = _load_stair_progress(project_id, capture_id, floor_id, db)
    return _stair_progress_result(
        project_id, capture_id, floor_id, stairs, entries,
        _stair_stages_for_floor(db, floor_id),
    )


@router.put(
    "/{project_id}/captures/{capture_id}/stair-progress",
    response_model=StairProgressRead,
)
def save_stair_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: StairProgressBulkCreate,
    db: DbSession,
    user: CurrentUser,
) -> StairProgressRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id,
        allowed_roles={"admin", "sub_admin", "reviewer"},
    )
    capture, stairs, _entries = _load_stair_progress(
        project_id, capture_id, payload.floor_id, db
    )
    stair_ids = {stair.id for stair in stairs}
    requested_ids = [entry.structural_element_id for entry in payload.entries]
    if len(set(requested_ids)) != len(requested_ids) or not set(requested_ids).issubset(stair_ids):
        raise HTTPException(status_code=422, detail="รายการบันไดไม่ถูกต้องหรือมีรหัสซ้ำ")
    stages = _stair_stages_for_floor(db, payload.floor_id)
    keyframe_ids = {
        entry.evidence_keyframe_id
        for entry in payload.entries
        if entry.evidence_keyframe_id is not None
    }
    valid_keyframes = set(db.scalars(select(Keyframe.id).where(
        Keyframe.capture_id == capture.id,
        Keyframe.id.in_(keyframe_ids),
    ))) if keyframe_ids else set()
    if valid_keyframes != keyframe_ids:
        raise HTTPException(status_code=422, detail="ภาพหลักฐานไม่ได้อยู่ใน Capture นี้")
    for item in payload.entries:
        if not set(item.completed_stages).issubset(stages):
            raise HTTPException(status_code=422, detail="ขั้นงานไม่ตรงกับชั้นของบันไดที่เลือก")
        db.add(StructuralElementProgressEntry(
            project_id=project_id,
            capture_id=capture_id,
            structural_element_id=item.structural_element_id,
            evidence_keyframe_id=item.evidence_keyframe_id,
            progress_percent=(
                Decimal(len(item.completed_stages)) / Decimal(len(stages)) * Decimal(100)
            ).quantize(Decimal("0.001")),
            stage_status_json={stage: stage in item.completed_stages for stage in stages},
            note=(item.note or "").strip() or None,
            entered_by_id=user.id,
        ))
    db.commit()
    _capture, stairs, entries = _load_stair_progress(
        project_id, capture_id, payload.floor_id, db
    )
    return _stair_progress_result(
        project_id, capture_id, payload.floor_id, stairs, entries, stages
    )


@router.get(
    "/{project_id}/captures/{capture_id}/slab-progress",
    response_model=SlabProgressRead,
)
def get_slab_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> SlabProgressRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    _capture, slabs, entries = _load_slab_progress(project_id, capture_id, floor_id, db)
    return _slab_progress_result(project_id, capture_id, floor_id, slabs, entries)


@router.put(
    "/{project_id}/captures/{capture_id}/slab-progress",
    response_model=SlabProgressRead,
)
def save_slab_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: SlabProgressBulkCreate,
    db: DbSession,
    user: CurrentUser,
) -> SlabProgressRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "sub_admin", "reviewer"}
    )
    capture, slabs, _entries = _load_slab_progress(
        project_id, capture_id, payload.floor_id, db
    )
    slab_by_id = {slab.id: slab for slab in slabs}
    slab_ids = set(slab_by_id)
    requested_ids = [entry.structural_element_id for entry in payload.entries]
    if len(set(requested_ids)) != len(requested_ids) or not set(requested_ids).issubset(slab_ids):
        raise HTTPException(status_code=422, detail="รายการพื้นที่พื้นไม่ถูกต้องหรือมีรหัสซ้ำ")
    keyframe_ids = {
        entry.evidence_keyframe_id
        for entry in payload.entries
        if entry.evidence_keyframe_id is not None
    }
    valid_keyframes = set(db.scalars(select(Keyframe.id).where(
        Keyframe.capture_id == capture.id,
        Keyframe.id.in_(keyframe_ids),
    ))) if keyframe_ids else set()
    if valid_keyframes != keyframe_ids:
        raise HTTPException(status_code=422, detail="ภาพหลักฐานไม่ได้อยู่ใน Capture นี้")
    for item in payload.entries:
        required_stages = _slab_stage_codes(slab_by_id[item.structural_element_id])
        if not set(item.completed_stages).issubset(required_stages):
            raise HTTPException(
                status_code=422,
                detail="ขั้นงานไม่ตรงกับประเภทพื้น GS/S1/PC1 ที่เลือก",
            )
        db.add(StructuralElementProgressEntry(
            project_id=project_id,
            capture_id=capture_id,
            structural_element_id=item.structural_element_id,
            evidence_keyframe_id=item.evidence_keyframe_id,
            progress_percent=(
                Decimal(len(item.completed_stages))
                / Decimal(len(required_stages))
                * Decimal(100)
            ).quantize(Decimal("0.001")),
            stage_status_json={stage: stage in item.completed_stages for stage in SLAB_STAGES},
            note=(item.note or "").strip() or None,
            entered_by_id=user.id,
        ))
    db.commit()
    _capture, slabs, entries = _load_slab_progress(
        project_id, capture_id, payload.floor_id, db
    )
    return _slab_progress_result(project_id, capture_id, payload.floor_id, slabs, entries)


@router.get(
    "/{project_id}/captures/{capture_id}/roof-progress",
    response_model=RoofProgressRead,
)
def get_roof_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> RoofProgressRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    _capture, roofs, entries = _load_roof_progress(
        project_id, capture_id, floor_id, db
    )
    return _roof_progress_result(project_id, capture_id, floor_id, roofs, entries)


@router.put(
    "/{project_id}/captures/{capture_id}/roof-progress",
    response_model=RoofProgressRead,
)
def save_roof_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: RoofProgressBulkCreate,
    db: DbSession,
    user: CurrentUser,
) -> RoofProgressRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "sub_admin", "reviewer"}
    )
    capture, roofs, previous_entries = _load_roof_progress(
        project_id, capture_id, payload.floor_id, db
    )
    roof_by_id = {roof.id: roof for roof in roofs}
    requested_ids = [entry.structural_element_id for entry in payload.entries]
    if (
        len(set(requested_ids)) != len(requested_ids)
        or not set(requested_ids).issubset(roof_by_id)
    ):
        raise HTTPException(status_code=422, detail="รายการชิ้นงานหลังคาไม่ถูกต้องหรือมีรหัสซ้ำ")
    keyframe_ids = {
        entry.evidence_keyframe_id
        for entry in payload.entries
        if entry.evidence_keyframe_id is not None
    }
    valid_keyframes = set(db.scalars(select(Keyframe.id).where(
        Keyframe.capture_id == capture.id,
        Keyframe.id.in_(keyframe_ids),
    ))) if keyframe_ids else set()
    if valid_keyframes != keyframe_ids:
        raise HTTPException(status_code=422, detail="ภาพหลักฐานไม่ได้อยู่ใน Capture นี้")

    latest_completed_quantity: dict[uuid.UUID, int] = {}
    for entry in previous_entries:
        roof = roof_by_id.get(entry.structural_element_id)
        if roof is not None:
            latest_completed_quantity.setdefault(
                entry.structural_element_id,
                _roof_completed_quantity(entry, _roof_total_quantity(roof)),
            )
    affected_wbs: set[str] = set()
    for item in payload.entries:
        roof = roof_by_id[item.structural_element_id]
        activity_wbs = str(roof.geometry_json.get("activity_wbs", ""))
        if not activity_wbs:
            raise HTTPException(status_code=422, detail="ชิ้นงานหลังคาไม่มีรหัสกิจกรรม WBS")
        affected_wbs.add(activity_wbs)
        count_mode = str(roof.geometry_json.get("progress_mode", "")).upper() == "COUNT"
        if item.total_quantity is not None:
            if not count_mode:
                raise HTTPException(status_code=422, detail="ชิ้นงานนี้ไม่ได้ตรวจแบบนับจำนวน")
            roof.geometry_json = {**roof.geometry_json, "total_quantity": item.total_quantity}
        total_quantity = _roof_total_quantity(roof)
        if count_mode:
            completed_quantity = (
                item.completed_quantity
                if item.completed_quantity is not None
                else total_quantity if item.complete else 0
            )
            if completed_quantity > total_quantity:
                raise HTTPException(
                    status_code=422,
                    detail="จำนวนที่ตรวจแล้วต้องไม่เกินจำนวนทั้งหมด",
                )
        else:
            if item.complete is None:
                raise HTTPException(status_code=422, detail="กรุณาระบุสถานะชิ้นงานหลังคา")
            completed_quantity = int(item.complete)
        complete = completed_quantity >= total_quantity
        latest_completed_quantity[item.structural_element_id] = completed_quantity
        progress_percent = (
            Decimal(completed_quantity) / Decimal(total_quantity) * Decimal(100)
        ).quantize(Decimal("0.001"))
        db.add(StructuralElementProgressEntry(
            project_id=project_id,
            capture_id=capture_id,
            structural_element_id=item.structural_element_id,
            evidence_keyframe_id=item.evidence_keyframe_id,
            progress_percent=progress_percent,
            stage_status_json={
                ROOF_COMPLETE_STAGE: complete,
                **({
                    "completed_quantity": completed_quantity,
                    "total_quantity": total_quantity,
                } if count_mode else {}),
            },
            note=(item.note or "").strip() or None,
            entered_by_id=user.id,
        ))

    schedule = db.scalar(select(ScheduleVersion).where(
        ScheduleVersion.project_id == project_id,
        ScheduleVersion.status == "READY",
        ScheduleVersion.is_baseline.is_(True),
    ).order_by(ScheduleVersion.version_no.desc()))
    if schedule is None:
        schedule = db.scalar(select(ScheduleVersion).where(
            ScheduleVersion.project_id == project_id,
            ScheduleVersion.status == "READY",
        ).order_by(ScheduleVersion.version_no.desc()))
    activities_by_wbs = {
        activity.wbs: activity
        for activity in db.scalars(select(Activity).where(
            Activity.schedule_version_id == schedule.id,
            Activity.wbs.in_(affected_wbs),
        ))
    } if schedule else {}
    for activity_wbs in affected_wbs:
        activity = activities_by_wbs.get(activity_wbs)
        if activity is None:
            raise HTTPException(status_code=422, detail=f"ไม่พบกิจกรรมหลังคา {activity_wbs} ในแผนงาน")
        group = [
            roof for roof in roofs
            if str(roof.geometry_json.get("activity_wbs", "")) == activity_wbs
        ]
        total = sum(_roof_total_quantity(roof) for roof in group)
        completed = sum(
            latest_completed_quantity.get(roof.id, 0)
            for roof in group
        )
        percent = (
            Decimal(completed) / Decimal(total) * Decimal(100)
        ).quantize(Decimal("0.001")) if total else Decimal(0)
        db.add(HumanProgressEntry(
            project_id=project_id,
            activity_id=activity.id,
            capture_id=capture_id,
            observed_at=capture.captured_at,
            progress_percent=percent,
            note=f"ผลตรวจงานหลังคา {completed}/{total} หน่วย",
            entered_by_id=user.id,
        ))
    db.commit()
    _capture, roofs, entries = _load_roof_progress(
        project_id, capture_id, payload.floor_id, db
    )
    return _roof_progress_result(project_id, capture_id, payload.floor_id, roofs, entries)


@router.delete(
    "/{project_id}/captures/{capture_id}/roof-progress",
    response_model=RoofProgressRead,
)
def delete_roof_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: RoofProgressBulkDelete,
    db: DbSession,
    user: CurrentUser,
) -> RoofProgressRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "sub_admin", "reviewer"}
    )
    capture, roofs, _previous_entries = _load_roof_progress(
        project_id, capture_id, payload.floor_id, db
    )
    roof_by_id = {roof.id: roof for roof in roofs}
    requested_ids = payload.structural_element_ids
    if (
        len(set(requested_ids)) != len(requested_ids)
        or not set(requested_ids).issubset(roof_by_id)
    ):
        raise HTTPException(status_code=422, detail="รายการชิ้นงานหลังคาไม่ถูกต้องหรือมีรหัสซ้ำ")

    current_entry_ids = list(db.scalars(select(StructuralElementProgressEntry.id).where(
        StructuralElementProgressEntry.project_id == project_id,
        StructuralElementProgressEntry.capture_id == capture_id,
        StructuralElementProgressEntry.structural_element_id.in_(requested_ids),
    )))
    if not current_entry_ids:
        raise HTTPException(status_code=404, detail="ไม่พบผลตรวจของวันนี้สำหรับรายการที่เลือก")

    affected_wbs = {
        str(roof_by_id[element_id].geometry_json.get("activity_wbs", ""))
        for element_id in requested_ids
    }
    affected_wbs.discard("")
    db.execute(delete(StructuralElementProgressEntry).where(
        StructuralElementProgressEntry.id.in_(current_entry_ids)
    ))
    db.flush()

    schedule = db.scalar(select(ScheduleVersion).where(
        ScheduleVersion.project_id == project_id,
        ScheduleVersion.status == "READY",
        ScheduleVersion.is_baseline.is_(True),
    ).order_by(ScheduleVersion.version_no.desc()))
    if schedule is None:
        schedule = db.scalar(select(ScheduleVersion).where(
            ScheduleVersion.project_id == project_id,
            ScheduleVersion.status == "READY",
        ).order_by(ScheduleVersion.version_no.desc()))
    activities_by_wbs = {
        activity.wbs: activity
        for activity in db.scalars(select(Activity).where(
            Activity.schedule_version_id == schedule.id,
            Activity.wbs.in_(affected_wbs),
        ))
    } if schedule else {}

    _capture, updated_roofs, updated_entries = _load_roof_progress(
        project_id, capture_id, payload.floor_id, db
    )
    latest: dict[uuid.UUID, StructuralElementProgressEntry] = {}
    for entry in updated_entries:
        latest.setdefault(entry.structural_element_id, entry)

    for activity_wbs in affected_wbs:
        activity = activities_by_wbs.get(activity_wbs)
        if activity is None:
            continue
        db.execute(delete(HumanProgressEntry).where(
            HumanProgressEntry.project_id == project_id,
            HumanProgressEntry.capture_id == capture_id,
            HumanProgressEntry.activity_id == activity.id,
            HumanProgressEntry.note.like("ผลตรวจงานหลังคา %"),
        ))
        group = [
            roof for roof in updated_roofs
            if str(roof.geometry_json.get("activity_wbs", "")) == activity_wbs
        ]
        has_current_entry = any(
            latest_entry.capture_id == capture_id
            for roof in group
            if (latest_entry := latest.get(roof.id)) is not None
        )
        if not has_current_entry:
            continue
        total = sum(_roof_total_quantity(roof) for roof in group)
        completed = sum(
            _roof_completed_quantity(latest.get(roof.id), _roof_total_quantity(roof))
            for roof in group
        )
        percent = (
            Decimal(completed) / Decimal(total) * Decimal(100)
        ).quantize(Decimal("0.001")) if total else Decimal(0)
        db.add(HumanProgressEntry(
            project_id=project_id,
            activity_id=activity.id,
            capture_id=capture_id,
            observed_at=capture.captured_at,
            progress_percent=percent,
            note=f"ผลตรวจงานหลังคา {completed}/{total} หน่วย",
            entered_by_id=user.id,
        ))

    db.commit()
    _capture, updated_roofs, updated_entries = _load_roof_progress(
        project_id, capture_id, payload.floor_id, db
    )
    return _roof_progress_result(
        project_id, capture_id, payload.floor_id, updated_roofs, updated_entries
    )


@router.post(
    "/{project_id}/captures/{capture_id}/beam-ai/run",
    response_model=BeamProgressRead,
    deprecated=True,
)
def run_beam_ai(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: BeamProgressAIRequest,
    db: DbSession,
    user: CurrentUser,
) -> BeamProgressRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "sub_admin", "reviewer"}
    )
    raise HTTPException(
        status_code=410,
        detail="ยกเลิกการใช้ AI ตรวจ Progress แล้ว กรุณาบันทึกผลตรวจโดยผู้ใช้",
    )

    # Legacy implementation is retained below only to preserve historical behavior
    # while existing prediction rows remain available for audit.
    capture, segments, entries, _predictions = _load_beam_progress(
        project_id, capture_id, payload.floor_id, db
    )
    if capture.status != "READY":
        raise HTTPException(status_code=409, detail="Capture ต้องประมวลผลตำแหน่งให้ READY ก่อน")
    if not segments:
        raise HTTPException(status_code=409, detail="ยังไม่มีรายการคานบนแปลนชั้นนี้")
    if capture.dataset_split == "HOLDOUT_TEST" and any(
        prediction.model_version == MODEL_VERSION
        for prediction in _predictions
    ):
        raise HTTPException(
            status_code=409,
            detail="ผล AI ของชุดทดสอบถูกตรึงแล้ว ห้ามวิเคราะห์ซ้ำก่อนบันทึก Ground Truth",
        )
    try:
        run_beam_progress_inference(
            db,
            project_id=project_id,
            capture=capture,
            floor_id=payload.floor_id,
            segments=segments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _capture, segments, entries, predictions = _load_beam_progress(
        project_id, capture_id, payload.floor_id, db
    )
    return _beam_progress_result(
        project_id, capture_id, payload.floor_id, segments, entries, predictions,
        _beam_stages_for_floor(db, payload.floor_id),
    )


@router.get(
    "/{project_id}/beam-ai/evaluation",
    response_model=BeamAIEvaluationRead,
    deprecated=True,
)
def evaluate_beam_ai(
    project_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> BeamAIEvaluationRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    raise HTTPException(
        status_code=410,
        detail="ยกเลิกการประเมิน AI Progress แล้ว ผลตรวจโดยผู้ใช้เป็นค่า Actual หลัก",
    )

    # Historical evaluation code remains in place so old prediction data is not
    # destructively migrated or silently reinterpreted.
    captures = list(
        db.scalars(
            select(Capture)
            .where(
                Capture.project_id == project_id,
                Capture.dataset_split == "HOLDOUT_TEST",
            )
            .order_by(Capture.captured_at)
        )
    )
    capture_metrics: list[BeamAICaptureEvaluation] = []
    all_errors: list[Decimal] = []
    total_tp = total_fp = total_fn = 0
    for capture in captures:
        human_rows = list(
            db.scalars(
                select(BeamProgressEntry)
                .where(BeamProgressEntry.capture_id == capture.id)
                .order_by(BeamProgressEntry.created_at.desc())
            )
        )
        prediction_rows = list(
            db.scalars(
                select(BeamProgressPrediction)
                .where(
                    BeamProgressPrediction.capture_id == capture.id,
                    BeamProgressPrediction.model_version == MODEL_VERSION,
                )
                .order_by(BeamProgressPrediction.created_at.desc())
            )
        )
        latest_human: dict[uuid.UUID, BeamProgressEntry] = {}
        latest_prediction: dict[uuid.UUID, BeamProgressPrediction] = {}
        for row in human_rows:
            latest_human.setdefault(row.beam_segment_id, row)
        for row in prediction_rows:
            latest_prediction.setdefault(row.beam_segment_id, row)
        paired = [
            (latest_human[segment_id], prediction)
            for segment_id, prediction in latest_prediction.items()
            if segment_id in latest_human and prediction.progress_percent is not None
        ]
        if not paired:
            continue
        lengths = {
            segment.id: segment.length_m or Decimal(1)
            for segment in db.scalars(
                select(BeamSegment).where(
                    BeamSegment.id.in_({human.beam_segment_id for human, _ in paired})
                )
            )
        }
        total_weight = sum(
            (lengths.get(human.beam_segment_id, Decimal(1)) for human, _ in paired),
            Decimal(0),
        )
        human_actual = sum(
            (
                human.progress_percent
                * lengths.get(human.beam_segment_id, Decimal(1))
                for human, _ in paired
            ),
            Decimal(0),
        ) / total_weight
        ai_actual = sum(
            (
                prediction.progress_percent
                * lengths.get(human.beam_segment_id, Decimal(1))
                for human, prediction in paired
                if prediction.progress_percent is not None
            ),
            Decimal(0),
        ) / total_weight
        errors = [
            abs(human.progress_percent - prediction.progress_percent)
            for human, prediction in paired
            if prediction.progress_percent is not None
        ]
        tp = sum(
            human.progress_percent >= 40 and prediction.progress_percent >= 40
            for human, prediction in paired
            if prediction.progress_percent is not None
        )
        fp = sum(
            human.progress_percent < 40 and prediction.progress_percent >= 40
            for human, prediction in paired
            if prediction.progress_percent is not None
        )
        fn = sum(
            human.progress_percent >= 40 and prediction.progress_percent < 40
            for human, prediction in paired
            if prediction.progress_percent is not None
        )
        denominator = 2 * tp + fp + fn
        capture_metrics.append(
            BeamAICaptureEvaluation(
                capture_id=capture.id,
                captured_at=capture.captured_at,
                segment_count=len(paired),
                human_actual_percent=human_actual.quantize(Decimal("0.001")),
                ai_actual_percent=ai_actual.quantize(Decimal("0.001")),
                mae_pp=(sum(errors, Decimal(0)) / len(errors)).quantize(Decimal("0.001")),
                within_15_rate_percent=(
                    Decimal(sum(error <= 15 for error in errors))
                    / Decimal(len(errors))
                    * Decimal(100)
                ).quantize(Decimal("0.001")),
                installed_f1=(Decimal(2 * tp) / Decimal(denominator)).quantize(
                    Decimal("0.001")
                )
                if denominator
                else None,
            )
        )
        all_errors.extend(errors)
        total_tp += tp
        total_fp += fp
        total_fn += fn
    overall_denominator = 2 * total_tp + total_fp + total_fn
    mae = (
        (sum(all_errors, Decimal(0)) / len(all_errors)).quantize(Decimal("0.001"))
        if all_errors
        else None
    )
    f1 = (
        (Decimal(2 * total_tp) / Decimal(overall_denominator)).quantize(Decimal("0.001"))
        if overall_denominator
        else None
    )
    return BeamAIEvaluationRead(
        project_id=project_id,
        model_version=MODEL_VERSION,
        capture_count=len(capture_metrics),
        segment_count=len(all_errors),
        mae_pp=mae,
        within_15_rate_percent=(
            Decimal(sum(error <= 15 for error in all_errors))
            / Decimal(len(all_errors))
            * Decimal(100)
        ).quantize(Decimal("0.001"))
        if all_errors
        else None,
        installed_f1=f1,
        passes_mae=mae is not None and mae <= 15,
        passes_f1=f1 is not None and f1 >= Decimal("0.75"),
        captures=capture_metrics,
    )


@router.get(
    "/{project_id}/captures/{capture_id}/work-progress",
    response_model=WorkProgressRead,
)
def get_work_progress(
    project_id: uuid.UUID, capture_id: uuid.UUID, floor_id: uuid.UUID,
    db: DbSession, user: CurrentUser,
) -> WorkProgressRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    _capture, items, entries, predictions = _load_work_progress(
        project_id, capture_id, floor_id, db
    )
    return _work_progress_result(project_id, capture_id, floor_id, items, entries, predictions)


@router.put(
    "/{project_id}/captures/{capture_id}/work-progress",
    response_model=WorkProgressRead,
)
def save_work_progress(
    project_id: uuid.UUID, capture_id: uuid.UUID, payload: WorkProgressBulkCreate,
    db: DbSession, user: CurrentUser,
) -> WorkProgressRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "sub_admin", "reviewer"}
    )
    _capture, items, _entries, _predictions = _load_work_progress(
        project_id, capture_id, payload.floor_id, db
    )
    valid_item_ids = {item.id for item in items}
    requested_ids = [entry.work_item_id for entry in payload.entries]
    if len(requested_ids) != len(set(requested_ids)) or not set(
        requested_ids
    ).issubset(valid_item_ids):
        raise HTTPException(status_code=422, detail="รายการงานไม่ถูกต้องหรือมีรหัสซ้ำ")
    evidence_ids = {row.evidence_keyframe_id for row in payload.entries if row.evidence_keyframe_id}
    valid_evidence = set(db.scalars(select(Keyframe.id).where(
        Keyframe.capture_id == capture_id, Keyframe.id.in_(evidence_ids)
    ))) if evidence_ids else set()
    if evidence_ids != valid_evidence:
        raise HTTPException(status_code=422, detail="ภาพหลักฐานไม่ได้อยู่ใน Capture นี้")
    for row in payload.entries:
        db.add(WorkProgressEntry(
            project_id=project_id, capture_id=capture_id, work_item_id=row.work_item_id,
            evidence_keyframe_id=row.evidence_keyframe_id,
            progress_percent=row.progress_percent, note=(row.note or "").strip() or None,
            entered_by_id=user.id,
        ))
    db.commit()
    _capture, items, entries, predictions = _load_work_progress(
        project_id, capture_id, payload.floor_id, db
    )
    return _work_progress_result(
        project_id, capture_id, payload.floor_id, items, entries, predictions
    )


@router.post(
    "/{project_id}/captures/{capture_id}/work-ai/run",
    response_model=WorkProgressRead,
    deprecated=True,
)
def run_work_ai(
    project_id: uuid.UUID, capture_id: uuid.UUID, payload: WorkProgressAIRequest,
    db: DbSession, user: CurrentUser,
) -> WorkProgressRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "sub_admin", "reviewer"}
    )
    raise HTTPException(
        status_code=410,
        detail="ยกเลิกการใช้ AI ตรวจ Progress แล้ว กรุณาบันทึกผลตรวจโดยผู้ใช้",
    )

    # Legacy implementation is retained below only to preserve historical behavior
    # while existing prediction rows remain available for audit.
    capture, items, entries, predictions = _load_work_progress(
        project_id, capture_id, payload.floor_id, db
    )
    if capture.status != "READY":
        raise HTTPException(status_code=409, detail="Capture ต้องมีสถานะ READY ก่อนวิเคราะห์ AI")
    if capture.dataset_split == "HOLDOUT_TEST" and any(
        prediction.model_version == WORK_MODEL_VERSION for prediction in predictions
    ):
        raise HTTPException(status_code=409, detail="ผล AI ของชุดทดสอบถูกตรึงแล้ว")
    try:
        run_work_progress_inference(
            db, project_id=project_id, capture=capture, items=items
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _capture, items, entries, predictions = _load_work_progress(
        project_id, capture_id, payload.floor_id, db
    )
    return _work_progress_result(
        project_id, capture_id, payload.floor_id, items, entries, predictions
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _planned_percent(start: datetime, finish: datetime, observed_at: datetime) -> Decimal:
    start = _aware(start)
    finish = _aware(finish)
    observed_at = _aware(observed_at)
    if observed_at < start:
        return Decimal(0)
    if observed_at >= finish or finish <= start:
        return Decimal(100)
    elapsed = Decimal(str((observed_at - start).total_seconds()))
    duration = Decimal(str((finish - start).total_seconds()))
    return min(Decimal(100), max(Decimal(0), (elapsed / duration) * Decimal(100))).quantize(
        Decimal("0.001")
    )


def _ground_beam_activity_percent(overall: Decimal, wbs: str) -> Decimal | None:
    """Map the 0-100 construction milestone scale to each schedule activity."""
    if wbs == "1.2.1.2":
        return overall
    thresholds = {
        "1.2.1.2.1": Decimal(20),  # rebar: 20 -> 40
        "1.2.1.2.2": Decimal(40),  # formwork: 40 -> 60
        "1.2.1.2.3": Decimal(60),  # concrete: 60 -> 80
        "1.2.1.2.4": Decimal(80),  # stripping/inspection: 80 -> 100
    }
    start = thresholds.get(wbs)
    if start is None:
        return None
    return min(Decimal(100), max(Decimal(0), (overall - start) * Decimal(5))).quantize(
        Decimal("0.001")
    )


def _latest_entry_observed_at(
    db: DbSession,
    entries: list[BeamProgressEntry] | list[StructuralElementProgressEntry],
) -> datetime | None:
    """Return the capture time represented by the newest detailed inspection."""
    observed_at: datetime | None = None
    capture_times: dict[uuid.UUID, datetime] = {}
    for entry in entries:
        if entry.capture_id not in capture_times:
            entry_capture = db.get(Capture, entry.capture_id)
            if entry_capture is not None:
                capture_times[entry.capture_id] = entry_capture.captured_at
        candidate = capture_times.get(entry.capture_id)
        if candidate is not None and (observed_at is None or candidate > observed_at):
            observed_at = candidate
    return observed_at


def _slab_type_stage_percent(
    slabs: list[StructuralElement],
    entries: list[StructuralElementProgressEntry],
    slab_type: str | None,
    stage: str,
) -> Decimal | None:
    latest: dict[uuid.UUID, StructuralElementProgressEntry] = {}
    for entry in entries:
        latest.setdefault(entry.structural_element_id, entry)
    matching = [slab for slab in slabs if slab_type is None or _slab_type(slab) == slab_type]
    if not matching or not any(slab.id in latest for slab in matching):
        return None
    total_area = sum((_slab_area_m2(slab) for slab in matching), Decimal(0))
    if not total_area:
        return Decimal(0)
    completed_area = sum(
        (
            _slab_area_m2(slab)
            for slab in matching
            if slab.id in latest
            if stage in _normalized_slab_stages(
                slab,
                latest[slab.id].stage_status_json,
            )
        ),
        Decimal(0),
    )
    return (completed_area / total_area * Decimal(100)).quantize(Decimal("0.001"))


def _detailed_structural_actuals(
    db: DbSession,
    project_id: uuid.UUID,
    capture: Capture,
) -> dict[str, tuple[Decimal, datetime | None]]:
    """Map immutable per-element inspections to schedule leaf WBS rows."""
    actuals: dict[str, tuple[Decimal, datetime | None]] = {}
    floors = list(
        db.scalars(
            select(Floor)
            .where(Floor.project_id == project_id)
            .order_by(Floor.level_index)
        )
    )
    for floor in floors:
        level = floor.level_index
        if 1 <= level <= 4:
            _beam_capture, segments, beam_entries, predictions = _load_beam_progress(
                project_id, capture.id, floor.id, db
            )
            beam_result = _beam_progress_result(
                project_id, capture.id, floor.id, segments, beam_entries, predictions,
                _beam_stages_for_floor(db, floor.id),
            )
            if beam_result.labeled_count:
                observed_at = _latest_entry_observed_at(db, beam_entries)
                stage_percent = {
                    item.stage: item.progress_percent
                    for item in beam_result.stage_summaries
                }
                if level == 1:
                    beam_base = "1.2.1.3"
                    beam_stages = FLOOR_ONE_BEAM_STAGES
                    if beam_result.weighted_progress_percent is not None:
                        # Some legacy schedules use 1.2.1.2 for ground beams,
                        # while the project's current schedule uses it for
                        # pedestals.  Keep the value under an internal key and
                        # apply it only when the activity name identifies a beam.
                        actuals["__FLOOR_1_BEAM_OVERALL__"] = (
                            beam_result.weighted_progress_percent,
                            observed_at,
                        )
                else:
                    beam_base = f"1.2.{level}.1"
                    beam_stages = UPPER_FLOOR_BEAM_STAGES
                for suffix, stage in enumerate(beam_stages, 1):
                    actuals[f"{beam_base}.{suffix}"] = (
                        stage_percent.get(stage, Decimal(0)),
                        observed_at,
                    )

            _column_capture, columns, column_entries = _load_column_progress(
                project_id, capture.id, floor.id, db
            )
            column_result = _column_progress_result(
                project_id, capture.id, floor.id, columns, column_entries
            )
            if column_result.labeled_count:
                observed_at = _latest_entry_observed_at(db, column_entries)
                column_base = "1.2.1.5" if level == 1 else f"1.2.{level}.3"
                for suffix, summary in enumerate(column_result.stage_summaries, 1):
                    actuals[f"{column_base}.{suffix}"] = (
                        summary.progress_percent,
                        observed_at,
                    )

            _slab_capture, slabs, slab_entries = _load_slab_progress(
                project_id, capture.id, floor.id, db
            )
            if slab_entries:
                observed_at = _latest_entry_observed_at(db, slab_entries)
                if level == 1:
                    slab_mapping = {
                        "1.2.1.4.1": ("GS", "SOIL_COMPACTION"),
                        "1.2.1.4.2": ("GS", "REBAR"),
                        "1.2.1.4.3": ("S1", "REBAR"),
                        "1.2.1.4.4": ("GS", "CONCRETE"),
                        "1.2.1.4.5": ("S1", "CONCRETE"),
                    }
                else:
                    slab_base = f"1.2.{level}.2"
                    slab_mapping = {
                        f"{slab_base}.1": (None, "SHORING"),
                        f"{slab_base}.2": ("PC1", "PLACE_PRECAST"),
                        f"{slab_base}.3": ("S1", "REBAR"),
                        f"{slab_base}.4": ("S1", "FORMWORK"),
                        f"{slab_base}.5": ("S1", "CONCRETE"),
                        f"{slab_base}.6": ("PC1", "CONCRETE"),
                    }
                for wbs, (slab_type, stage) in slab_mapping.items():
                    value = _slab_type_stage_percent(
                        slabs, slab_entries, slab_type, stage
                    )
                    if value is not None:
                        actuals[wbs] = (value, observed_at)

            _stair_capture, stairs, stair_entries = _load_stair_progress(
                project_id, capture.id, floor.id, db
            )
            stair_result = _stair_progress_result(
                project_id, capture.id, floor.id, stairs, stair_entries,
                _stair_stages_for_floor(db, floor.id),
            )
            if stair_result.labeled_count:
                observed_at = _latest_entry_observed_at(db, stair_entries)
                stair_base = "1.2.1.6" if level == 1 else f"1.2.{level}.4"
                for suffix, summary in enumerate(stair_result.stage_summaries, 1):
                    actuals[f"{stair_base}.{suffix}"] = (
                        summary.progress_percent,
                        observed_at,
                    )

        if level in {5, 6}:
            _roof_capture, roofs, roof_entries = _load_roof_progress(
                project_id, capture.id, floor.id, db
            )
            if roof_entries:
                observed_at = _latest_entry_observed_at(db, roof_entries)
                latest: dict[uuid.UUID, StructuralElementProgressEntry] = {}
                for entry in roof_entries:
                    latest.setdefault(entry.structural_element_id, entry)
                grouped: dict[str, list[StructuralElement]] = {}
                for roof in roofs:
                    activity_wbs = str(roof.geometry_json.get("activity_wbs", ""))
                    if activity_wbs:
                        grouped.setdefault(activity_wbs, []).append(roof)
                for activity_wbs, group in grouped.items():
                    if not any(roof.id in latest for roof in group):
                        continue
                    total = sum(_roof_total_quantity(roof) for roof in group)
                    completed = sum(
                        _roof_completed_quantity(
                            latest[roof.id], _roof_total_quantity(roof)
                        )
                        if roof.id in latest
                        else 0
                        for roof in group
                    )
                    value = (
                        Decimal(completed) / Decimal(total) * Decimal(100)
                    ).quantize(Decimal("0.001")) if total else Decimal(0)
                    actuals[activity_wbs] = (value, observed_at)
    return actuals


@router.get("/{project_id}/progress/manual", response_model=list[HumanProgressRead])
def list_human_progress(
    project_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[HumanProgressEntry]:
    require_project_role(db, project_id=project_id, user_id=user.id)
    rows = list(
        db.execute(
            select(HumanProgressEntry, Activity.wbs)
            .join(Activity, HumanProgressEntry.activity_id == Activity.id)
            .where(HumanProgressEntry.project_id == project_id)
            .order_by(
                HumanProgressEntry.observed_at.desc(), HumanProgressEntry.created_at.desc()
            )
        )
    )
    entries: list[HumanProgressEntry] = []
    for entry, activity_wbs in rows:
        entry.activity_wbs = activity_wbs
        entries.append(entry)
    return entries


@router.post(
    "/{project_id}/progress/manual",
    response_model=HumanProgressRead,
    status_code=status.HTTP_201_CREATED,
)
def create_human_progress(
    project_id: uuid.UUID,
    payload: HumanProgressCreate,
    db: DbSession,
    user: CurrentUser,
) -> HumanProgressEntry:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin", "sub_admin", "reviewer"},
    )
    activity = db.get(Activity, payload.activity_id)
    schedule = (
        db.get(ScheduleVersion, activity.schedule_version_id) if activity is not None else None
    )
    capture = db.get(Capture, payload.capture_id) if payload.capture_id else None
    if activity is None or schedule is None or schedule.project_id != project_id:
        raise HTTPException(status_code=422, detail="กิจกรรมไม่อยู่ในโครงการนี้")
    if payload.capture_id is not None and (capture is None or capture.project_id != project_id):
        raise HTTPException(status_code=422, detail="Capture ไม่อยู่ในโครงการนี้")
    entry = HumanProgressEntry(
        project_id=project_id,
        activity_id=activity.id,
        capture_id=payload.capture_id,
        observed_at=payload.observed_at,
        progress_percent=payload.progress_percent,
        note=(payload.note or "").strip() or None,
        entered_by_id=user.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    entry.activity_wbs = activity.wbs
    return entry


@router.post(
    "/{project_id}/progress/manual/bulk",
    response_model=list[HumanProgressRead],
    status_code=status.HTTP_201_CREATED,
)
def create_human_progress_bulk(
    project_id: uuid.UUID,
    payload: HumanProgressBulkCreate,
    db: DbSession,
    user: CurrentUser,
) -> list[HumanProgressEntry]:
    """Save one immutable human observation for every selected activity atomically."""
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin", "sub_admin", "reviewer"},
    )
    activity_ids = [row.activity_id for row in payload.entries]
    if len(activity_ids) != len(set(activity_ids)):
        raise HTTPException(status_code=422, detail="รายการงานมีรหัสซ้ำ")
    activities = {
        activity.id: activity
        for activity in db.scalars(
            select(Activity)
            .join(ScheduleVersion, Activity.schedule_version_id == ScheduleVersion.id)
            .where(
                Activity.id.in_(activity_ids),
                ScheduleVersion.project_id == project_id,
            )
        )
    }
    if set(activity_ids) != set(activities):
        raise HTTPException(status_code=422, detail="มีกิจกรรมที่ไม่อยู่ในโครงการนี้")
    capture_ids = {row.capture_id for row in payload.entries if row.capture_id is not None}
    valid_capture_ids = set(db.scalars(select(Capture.id).where(
        Capture.id.in_(capture_ids),
        Capture.project_id == project_id,
    ))) if capture_ids else set()
    if capture_ids != valid_capture_ids:
        raise HTTPException(status_code=422, detail="มี Capture ที่ไม่อยู่ในโครงการนี้")

    saved: list[HumanProgressEntry] = []
    for row in payload.entries:
        entry = HumanProgressEntry(
            project_id=project_id,
            activity_id=row.activity_id,
            capture_id=row.capture_id,
            observed_at=row.observed_at,
            progress_percent=row.progress_percent,
            note=(row.note or "").strip() or None,
            entered_by_id=user.id,
        )
        db.add(entry)
        saved.append(entry)
    db.commit()
    for entry in saved:
        db.refresh(entry)
        entry.activity_wbs = activities[entry.activity_id].wbs
    return saved


@router.get("/{project_id}/progress/comparison", response_model=ProgressComparisonRead)
def compare_progress(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> ProgressComparisonRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    capture = db.get(Capture, capture_id)
    if capture is None or capture.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบ Capture")
    schedule = db.scalar(
        select(ScheduleVersion)
        .where(
            ScheduleVersion.project_id == project_id,
            ScheduleVersion.status == "READY",
        )
        .order_by(ScheduleVersion.is_baseline.desc(), ScheduleVersion.version_no.desc())
    )
    if schedule is None:
        raise HTTPException(status_code=409, detail="กรุณา Import Schedule ก่อน")
    activities = list(
        db.scalars(
            select(Activity)
            .where(Activity.schedule_version_id == schedule.id)
            .order_by(Activity.source_row_no)
        )
    )
    human_rows = list(
        db.execute(
            select(HumanProgressEntry, Activity.wbs)
            .join(Activity, HumanProgressEntry.activity_id == Activity.id)
            .where(
                HumanProgressEntry.project_id == project_id,
                HumanProgressEntry.observed_at <= capture.captured_at,
            )
            .order_by(
                HumanProgressEntry.activity_id,
                HumanProgressEntry.observed_at.desc(),
                HumanProgressEntry.created_at.desc(),
            )
        )
    )
    latest_human: dict[uuid.UUID, HumanProgressEntry] = {}
    latest_human_by_wbs: dict[str, HumanProgressEntry] = {}
    for row, activity_wbs in human_rows:
        latest_human.setdefault(row.activity_id, row)
        latest_human_by_wbs.setdefault(activity_wbs, row)
    detailed_actuals = _detailed_structural_actuals(db, project_id, capture)
    items: list[ProgressComparisonItem] = []
    for activity in activities:
        planned = _planned_percent(
            activity.planned_start, activity.planned_finish, capture.captured_at
        )
        human = latest_human.get(activity.id) or latest_human_by_wbs.get(activity.wbs)
        detailed = detailed_actuals.get(activity.wbs)
        if detailed is None and "คาน" in activity.name:
            floor_one_beam = detailed_actuals.get("__FLOOR_1_BEAM_OVERALL__")
            mapped = (
                _ground_beam_activity_percent(floor_one_beam[0], activity.wbs)
                if floor_one_beam is not None
                else None
            )
            if mapped is not None:
                detailed = (mapped, floor_one_beam[1])
        actual = detailed[0] if detailed is not None else (
            human.progress_percent if human else None
        )
        observed_at = detailed[1] if detailed is not None else (
            human.observed_at if human else None
        )
        items.append(
            ProgressComparisonItem(
                activity_id=activity.id,
                wbs=activity.wbs,
                name=activity.name,
                planned_percent=planned,
                human_actual_percent=actual,
                human_observed_at=observed_at,
                variance_pp=(actual - planned).quantize(Decimal("0.001"))
                if actual is not None
                else None,
            )
        )
    return ProgressComparisonRead(
        project_id=project_id,
        capture_id=capture.id,
        capture_date=capture.captured_at,
        schedule_version_id=schedule.id,
        schedule_name=schedule.name,
        items=items,
    )
