from __future__ import annotations

import hashlib
import time
import uuid
from decimal import Decimal
from pathlib import Path

import cv2
from sqlalchemy import select
from sqlalchemy.orm import Session

from progress_api.models import (
    BeamProgressPrediction,
    BeamSegment,
    CameraPose,
    Capture,
    Keyframe,
    MediaFile,
)
from progress_api.object_storage import download_object
from progress_api.services.beam_full_scan import (
    FULL_SCAN_INTERVAL_MS,
    PanoramaFrame,
    evidence_for_plan_segment,
    observed_stage,
    scan_panoramas,
)
from progress_api.services.beam_visual_detector import GroundingDinoBeamDetector
from progress_api.services.temporary_workspace import temporary_workspace

MODEL_VERSION = "beam-grounding-dino-360-v3.1"
MAX_PLAN_DISTANCE = 0.18
STAGE_PROGRESS = {
    "REBAR": 25.0,
    "FORMWORK": 50.0,
    "CONCRETED": 75.0,
    "STRIPPED": 100.0,
}


def _select_timeline_rows(rows):
    if not rows:
        return []
    selected = [rows[0]]
    next_timestamp = rows[0][0].timestamp_ms + FULL_SCAN_INTERVAL_MS
    for row in rows[1:]:
        if row[0].timestamp_ms >= next_timestamp:
            selected.append(row)
            next_timestamp = row[0].timestamp_ms + FULL_SCAN_INTERVAL_MS
    if selected[-1][0].id != rows[-1][0].id:
        selected.append(rows[-1])
    return selected


def run_beam_progress_inference(
    db: Session,
    *,
    project_id: uuid.UUID,
    capture: Capture,
    floor_id: uuid.UUID,
    segments: list[BeamSegment],
) -> list[BeamProgressPrediction]:
    """Inspect actual beam objects over the full 360 video timeline.

    No date trend or whole-image progress heuristic is used. A stage is saved
    only when object boxes are observed at three or more distinct timestamps.
    """
    started = time.perf_counter()
    rows = list(
        db.execute(
            select(Keyframe, CameraPose, MediaFile)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
            .where(
                Keyframe.capture_id == capture.id,
                Keyframe.quality_status == "USABLE",
                CameraPose.floor_id == floor_id,
                CameraPose.needs_review.is_(False),
            )
            .order_by(Keyframe.timestamp_ms)
        ).all()
    )
    selected_rows = _select_timeline_rows(rows)
    if not selected_rows:
        raise ValueError("ไม่มีภาพ 360 ที่มีตำแหน่งกล้องผ่านการตรวจสำหรับชั้นนี้")

    fingerprint = hashlib.sha256(
        f"{MODEL_VERSION}:{capture.id}:{len(selected_rows)}".encode()
    ).hexdigest()
    predictions: list[BeamProgressPrediction] = []
    with temporary_workspace(prefix="beam-object-scan-") as directory:
        temp_dir = Path(directory)
        frames: list[PanoramaFrame] = []
        for keyframe, pose, media in selected_rows:
            destination = temp_dir / f"{keyframe.id}.jpg"
            download_object(key=media.object_key, destination=str(destination))
            image = cv2.imread(str(destination), cv2.IMREAD_COLOR)
            if image is None:
                continue
            frames.append(
                PanoramaFrame(
                    keyframe_id=keyframe.id,
                    timestamp_ms=keyframe.timestamp_ms,
                    image=image,
                    camera_x=float(pose.x),
                    camera_y=float(pose.y),
                    heading_deg=float(pose.heading_deg),
                )
            )
        if not frames:
            raise ValueError("อ่านภาพ 360 สำหรับตรวจคานไม่ได้")
        try:
            detector = GroundingDinoBeamDetector()
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        all_evidence = scan_panoramas(frames, detector, interval_ms=1)

        for segment in segments:
            midpoint = (
                (float(segment.start_x) + float(segment.end_x)) / 2,
                (float(segment.start_y) + float(segment.end_y)) / 2,
            )
            matches = evidence_for_plan_segment(
                all_evidence,
                segment_midpoint=midpoint,
                max_plan_distance=MAX_PLAN_DISTANCE,
            )
            detected_stage, confidence, support_count = observed_stage(matches)
            supporting = (
                [item for item in matches if item.stage == detected_stage]
                if detected_stage is not None
                else []
            )
            best = max(supporting, key=lambda item: item.score, default=None)
            needs_review = detected_stage is None or confidence < 0.60
            progress = (
                STAGE_PROGRESS[detected_stage]
                if detected_stage is not None and not needs_review
                else None
            )
            # Keep the observed candidate stage visible even when confidence is
            # below the acceptance gate. `needs_review` and a null percentage
            # prevent that candidate from being counted as measured progress.
            status = "NOT_VISIBLE" if detected_stage is None else detected_stage
            predictions.append(
                BeamProgressPrediction(
                    project_id=project_id,
                    capture_id=capture.id,
                    beam_segment_id=segment.id,
                    evidence_keyframe_id=best.keyframe_id if best is not None else None,
                    progress_percent=(
                        Decimal(str(progress)) if progress is not None else None
                    ),
                    status=status,
                    confidence=Decimal(str(round(confidence, 5))),
                    needs_review=needs_review,
                    model_version=MODEL_VERSION,
                    dataset_fingerprint=fingerprint,
                    # This field now records distinct supporting frames. It is
                    # retained for database compatibility with earlier models.
                    training_sample_count=support_count,
                    inference_ms=0,
                )
            )

    elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
    per_segment_ms = max(1, elapsed_ms // max(len(predictions), 1))
    for prediction in predictions:
        prediction.inference_ms = per_segment_ms
        db.add(prediction)
    db.commit()
    for prediction in predictions:
        db.refresh(prediction)
    return predictions
