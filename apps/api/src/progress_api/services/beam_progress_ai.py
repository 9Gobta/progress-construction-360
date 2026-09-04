from __future__ import annotations

import hashlib
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from progress_api.models import (
    BeamProgressEntry,
    BeamProgressPrediction,
    BeamSegment,
    CameraPose,
    Capture,
    Keyframe,
    MediaFile,
)
from progress_api.object_storage import download_object
from progress_api.services.temporary_workspace import temporary_workspace

MODEL_VERSION = "beam-multiview-stage-v2.1"
MIN_DEVELOPMENT_DATES = 3
MAX_EVIDENCE_VIEWS = 5
MIN_VIEW_SPACING_MS = 2_000
MAX_PLAN_DISTANCE = 0.18
MIN_VIEW_CONFIDENCE = 0.35
MIN_VISUAL_MATCH_CONFIDENCE = 0.45

STAGE_PROGRESS = {
    "NOT_STARTED": 0.0,
    "REBAR": 25.0,
    "FORMWORK": 50.0,
    "CONCRETED": 75.0,
    "STRIPPED": 100.0,
}


@dataclass(frozen=True)
class TrainingSample:
    segment_id: uuid.UUID
    capture_id: uuid.UUID
    captured_at_iso: str
    keyframe_id: uuid.UUID
    object_key: str
    progress: float
    camera_x: float
    camera_y: float
    heading_deg: float


@dataclass(frozen=True)
class EvidenceFrame:
    keyframe_id: uuid.UUID
    object_key: str
    timestamp_ms: int
    camera_x: float
    camera_y: float
    heading_deg: float
    view_confidence: float


def extract_visual_feature(image: np.ndarray) -> np.ndarray:
    """Compact deterministic descriptor for a stitched equirectangular frame."""
    resized = cv2.resize(image, (512, 256), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    values: list[float] = []
    for row in range(2):
        for column in range(4):
            patch = hsv[row * 128 : (row + 1) * 128, column * 128 : (column + 1) * 128]
            values.extend((patch.mean(axis=(0, 1)) / np.array([180, 255, 255])).tolist())
            values.extend((patch.std(axis=(0, 1)) / np.array([90, 128, 128])).tolist())
    for channel, bins, limit in ((0, 18, 180), (1, 12, 256), (2, 12, 256)):
        histogram = cv2.calcHist([hsv], [channel], None, [bins], [0, limit]).reshape(-1)
        histogram /= max(float(histogram.sum()), 1.0)
        values.extend(histogram.tolist())
    edges = cv2.Canny(gray, 60, 160)
    values.extend(
        [
            float(np.mean(edges > 0)),
            float(cv2.Laplacian(gray, cv2.CV_64F).var() / 10000.0),
            float(gray.mean() / 255.0),
            float(gray.std() / 128.0),
        ]
    )
    return np.asarray(values, dtype=np.float32)


def crop_beam_view(
    image: np.ndarray,
    *,
    camera_x: float,
    camera_y: float,
    heading_deg: float,
    segment: BeamSegment,
) -> np.ndarray:
    """Crop the upper 360 view facing one beam instead of describing the full frame.

    Camera poses and beam coordinates share normalized floor-plan coordinates.  The
    horizontal equirectangular position therefore comes from their relative bearing.
    A wide 100-degree crop is retained because localization and camera yaw are noisy.
    """
    height, width = image.shape[:2]
    midpoint_x = (float(segment.start_x) + float(segment.end_x)) / 2
    midpoint_y = (float(segment.start_y) + float(segment.end_y)) / 2
    bearing_deg = (
        math.degrees(math.atan2(midpoint_x - camera_x, -(midpoint_y - camera_y)))
        + 360.0
    ) % 360.0
    relative_deg = (bearing_deg - heading_deg + 360.0) % 360.0
    center_x = int(relative_deg / 360.0 * width)
    half_width = max(32, int(width * (100.0 / 360.0) / 2))
    indices = np.arange(center_x - half_width, center_x + half_width) % width
    horizontal = image[:, indices]
    # Structural beams appear above eye level. Keep a little lower context so the
    # classifier can distinguish rebar, formwork and cast concrete.
    top = int(height * 0.05)
    bottom = max(top + 32, int(height * 0.62))
    return horizontal[top:bottom]


def progress_stage(progress: float) -> str:
    if progress <= 5:
        return "NOT_STARTED"
    if progress <= 25:
        return "REBAR"
    if progress <= 50:
        return "FORMWORK"
    if progress <= 90:
        return "CONCRETED"
    return "STRIPPED"


def visual_stage_predict(
    train_features: np.ndarray,
    train_stages: list[str],
    target_feature: np.ndarray,
) -> tuple[str, float]:
    """Classify a visible construction stage using image evidence only."""
    if len(train_stages) != len(train_features):
        raise ValueError("train_stages and train_features must have equal length")
    scale = np.std(train_features, axis=0)
    scale[scale < 0.03] = 0.03
    mean = np.mean(train_features, axis=0)
    normalized = (train_features - mean) / scale
    target = (target_feature - mean) / scale
    distances = np.linalg.norm(normalized - target, axis=1) / math.sqrt(train_features.shape[1])
    neighbors = np.argsort(distances)[: min(5, len(train_stages))]
    votes: dict[str, float] = {}
    for index in neighbors:
        weight = 1.0 / max(float(distances[index]), 0.08)
        votes[train_stages[int(index)]] = votes.get(train_stages[int(index)], 0.0) + weight
    stage, winning_vote = max(votes.items(), key=lambda item: item[1])
    agreement = winning_vote / max(sum(votes.values()), 1e-6)
    proximity = math.exp(-float(distances[neighbors[0]]) / 2.0)
    confidence = max(0.0, min(1.0, 0.55 * proximity + 0.45 * agreement))
    return stage, confidence


def visual_knn_predict(
    train_features: np.ndarray,
    train_targets: np.ndarray,
    target_feature: np.ndarray,
) -> tuple[float, float]:
    """Return progress and confidence without an optional ML dependency."""
    scale = np.std(train_features, axis=0)
    scale[scale < 0.03] = 0.03
    normalized = (train_features - np.mean(train_features, axis=0)) / scale
    target = (target_feature - np.mean(train_features, axis=0)) / scale
    distances = np.linalg.norm(normalized - target, axis=1) / math.sqrt(train_features.shape[1])
    count = min(3, len(train_targets))
    neighbors = np.argsort(distances)[:count]
    weights = 1.0 / np.maximum(distances[neighbors], 0.08)
    prediction = float(np.average(train_targets[neighbors], weights=weights))
    proximity = math.exp(-float(distances[neighbors[0]]) / 2.5)
    agreement = max(0.0, 1.0 - float(np.std(train_targets[neighbors])) / 45.0)
    confidence = max(0.0, min(1.0, 0.65 * proximity + 0.35 * agreement))
    return max(0.0, min(100.0, prediction)), confidence


def temporal_progress_predict(
    captured_at_iso: list[str],
    train_targets: np.ndarray,
    target_captured_at_iso: str,
) -> tuple[float, float]:
    """Fit a monotonic construction trend and safely extrapolate to the target date."""
    timestamps = np.asarray(
        [datetime.fromisoformat(value).timestamp() for value in captured_at_iso],
        dtype=np.float64,
    )
    target_timestamp = datetime.fromisoformat(target_captured_at_iso).timestamp()
    origin = float(np.min(timestamps))
    days = (timestamps - origin) / 86400.0
    target_day = (target_timestamp - origin) / 86400.0
    slope, intercept = np.polyfit(days, train_targets.astype(np.float64), 1)
    slope = max(0.0, float(slope))
    fitted = np.clip(intercept + slope * days, 0.0, 100.0)
    prediction = float(np.clip(intercept + slope * target_day, 0.0, 100.0))
    residual_mae = float(np.mean(np.abs(fitted - train_targets)))
    confidence = max(0.0, min(1.0, 1.0 - residual_mae / 35.0))
    return prediction, confidence


def _latest_development_samples(
    db: Session,
    project_id: uuid.UUID,
    target_capture_id: uuid.UUID,
    target_captured_at: datetime,
) -> list[TrainingSample]:
    rows = db.execute(
        select(BeamProgressEntry, Capture)
        .join(Capture, Capture.id == BeamProgressEntry.capture_id)
        .where(
            BeamProgressEntry.project_id == project_id,
            BeamProgressEntry.capture_id != target_capture_id,
            Capture.dataset_split == "DEVELOPMENT",
            # A prediction may never learn from labels recorded after the target.
            Capture.captured_at < target_captured_at,
        )
        .order_by(BeamProgressEntry.created_at.desc())
    ).all()
    latest_entries: dict[tuple[uuid.UUID, uuid.UUID], tuple[BeamProgressEntry, Capture]] = {}
    for entry, capture in rows:
        key = (capture.id, entry.beam_segment_id)
        latest_entries.setdefault(key, (entry, capture))
    segments = {
        segment.id: segment
        for segment in db.scalars(
            select(BeamSegment).where(
                BeamSegment.id.in_({key[1] for key in latest_entries})
            )
        )
    }
    posed_frames: dict[uuid.UUID, list[tuple[Keyframe, CameraPose, MediaFile]]] = {}

    def frame_for(
        entry: BeamProgressEntry, capture: Capture
    ) -> tuple[Keyframe, CameraPose, MediaFile] | None:
        if entry.evidence_keyframe_id is not None:
            explicit = db.execute(
                select(Keyframe, CameraPose, MediaFile)
                .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
                .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
                .where(
                    Keyframe.id == entry.evidence_keyframe_id,
                    Keyframe.capture_id == capture.id,
                    Keyframe.quality_status == "USABLE",
                )
            ).first()
            if explicit is not None:
                return explicit[0], explicit[1], explicit[2]
        if capture.id not in posed_frames:
            posed_frames[capture.id] = list(
                db.execute(
                    select(Keyframe, CameraPose, MediaFile)
                    .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
                    .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
                    .where(
                        Keyframe.capture_id == capture.id,
                        Keyframe.quality_status == "USABLE",
                    )
                ).all()
            )
        segment = segments.get(entry.beam_segment_id)
        candidates = posed_frames[capture.id]
        if segment is None or not candidates:
            return None
        midpoint_x = (float(segment.start_x) + float(segment.end_x)) / 2
        midpoint_y = (float(segment.start_y) + float(segment.end_y)) / 2
        keyframe, _pose, media = min(
            candidates,
            key=lambda row: (float(row[1].x) - midpoint_x) ** 2
            + (float(row[1].y) - midpoint_y) ** 2,
        )
        return keyframe, _pose, media

    samples: list[TrainingSample] = []
    for entry, capture in latest_entries.values():
        evidence = frame_for(entry, capture)
        if evidence is None:
            continue
        keyframe, pose, media = evidence
        samples.append(
            TrainingSample(
                segment_id=entry.beam_segment_id,
                capture_id=capture.id,
                captured_at_iso=capture.captured_at.isoformat(),
                keyframe_id=keyframe.id,
                object_key=media.object_key,
                progress=float(entry.progress_percent),
                camera_x=float(pose.x),
                camera_y=float(pose.y),
                heading_deg=float(pose.heading_deg),
            )
        )
    return samples


def _target_evidence(
    db: Session,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    segments: list[BeamSegment],
) -> dict[uuid.UUID, list[EvidenceFrame]]:
    rows = db.execute(
        select(Keyframe, CameraPose, MediaFile)
        .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
        .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
        .where(
            Keyframe.capture_id == capture_id,
            Keyframe.quality_status == "USABLE",
            CameraPose.floor_id == floor_id,
            CameraPose.needs_review.is_(False),
        )
    ).all()
    result: dict[uuid.UUID, list[EvidenceFrame]] = {}
    for segment in segments:
        midpoint_x = (float(segment.start_x) + float(segment.end_x)) / 2
        midpoint_y = (float(segment.start_y) + float(segment.end_y)) / 2
        if not rows:
            continue
        ranked = sorted(
            rows,
            key=lambda row: (float(row[1].x) - midpoint_x) ** 2
            + (float(row[1].y) - midpoint_y) ** 2,
        )
        selected: list[EvidenceFrame] = []
        for keyframe, pose, media in ranked:
            distance = math.hypot(float(pose.x) - midpoint_x, float(pose.y) - midpoint_y)
            if distance > MAX_PLAN_DISTANCE:
                continue
            if any(
                abs(keyframe.timestamp_ms - item.timestamp_ms) < MIN_VIEW_SPACING_MS
                for item in selected
            ):
                continue
            view_confidence = float(pose.confidence) * math.exp(-distance / 0.12)
            if view_confidence < MIN_VIEW_CONFIDENCE:
                continue
            selected.append(
                EvidenceFrame(
                    keyframe_id=keyframe.id,
                    object_key=media.object_key,
                    timestamp_ms=keyframe.timestamp_ms,
                    camera_x=float(pose.x),
                    camera_y=float(pose.y),
                    heading_deg=float(pose.heading_deg),
                    view_confidence=view_confidence,
                )
            )
            if len(selected) == MAX_EVIDENCE_VIEWS:
                break
        if selected:
            result[segment.id] = selected
    return result


def _dataset_fingerprint(samples: list[TrainingSample]) -> str:
    payload = "|".join(
        sorted(
            f"{sample.capture_id}:{sample.segment_id}:{sample.keyframe_id}:{sample.progress:.3f}"
            for sample in samples
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _status(progress: float, confidence: float) -> tuple[str, bool]:
    if confidence < 0.45:
        return "NEEDS_REVIEW", True
    if progress <= 5:
        return "NOT_STARTED", False
    if progress >= 95:
        return "INSTALLED", False
    return "PARTIAL", confidence < 0.60


def run_beam_progress_inference(
    db: Session,
    *,
    project_id: uuid.UUID,
    capture: Capture,
    floor_id: uuid.UUID,
    segments: list[BeamSegment],
) -> list[BeamProgressPrediction]:
    started = time.perf_counter()
    samples = _latest_development_samples(
        db, project_id, capture.id, capture.captured_at
    )
    development_dates = {sample.captured_at_iso[:10] for sample in samples}
    if len(development_dates) < MIN_DEVELOPMENT_DATES:
        raise ValueError(
            f"ต้องมี Human Ground Truth อย่างน้อย {MIN_DEVELOPMENT_DATES} วันพัฒนา "
            "พร้อมภาพหลักฐานก่อนวิเคราะห์ AI"
        )
    fingerprint = _dataset_fingerprint(samples)
    target_frames = _target_evidence(db, capture.id, floor_id, segments)
    feature_cache: dict[str, np.ndarray] = {}

    def load_feature(
        object_key: str,
        temp_dir: Path,
        *,
        camera_x: float,
        camera_y: float,
        heading_deg: float,
        segment: BeamSegment,
    ) -> np.ndarray:
        cache_key = (
            f"{object_key}:{segment.id}:{camera_x:.6f}:"
            f"{camera_y:.6f}:{heading_deg:.3f}"
        )
        if cache_key not in feature_cache:
            destination = temp_dir / f"{hashlib.sha1(object_key.encode()).hexdigest()}.jpg"
            if not destination.is_file():
                download_object(key=object_key, destination=str(destination))
            image = cv2.imread(str(destination), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"อ่านภาพหลักฐานไม่ได้: {object_key}")
            roi = crop_beam_view(
                image,
                camera_x=camera_x,
                camera_y=camera_y,
                heading_deg=heading_deg,
                segment=segment,
            )
            feature_cache[cache_key] = extract_visual_feature(roi)
        return feature_cache[cache_key]

    predictions: list[BeamProgressPrediction] = []
    with temporary_workspace(prefix="beam-progress-") as directory:
        temp_dir = Path(directory)
        for segment in segments:
            segment_samples = [sample for sample in samples if sample.segment_id == segment.id]
            evidence_views = target_frames.get(segment.id, [])
            if not evidence_views or len(segment_samples) < MIN_DEVELOPMENT_DATES:
                predictions.append(
                    BeamProgressPrediction(
                        project_id=project_id,
                        capture_id=capture.id,
                        beam_segment_id=segment.id,
                        evidence_keyframe_id=(
                            evidence_views[0].keyframe_id if evidence_views else None
                        ),
                        progress_percent=None,
                        status="NOT_VISIBLE" if not evidence_views else "NEEDS_REVIEW",
                        confidence=Decimal("0"),
                        needs_review=True,
                        model_version=MODEL_VERSION,
                        dataset_fingerprint=fingerprint,
                        training_sample_count=len(segment_samples),
                        inference_ms=0,
                    )
                )
                continue
            train_features = np.stack(
                [
                    load_feature(
                        sample.object_key,
                        temp_dir,
                        camera_x=sample.camera_x,
                        camera_y=sample.camera_y,
                        heading_deg=sample.heading_deg,
                        segment=segment,
                    )
                    for sample in segment_samples
                ]
            )
            train_stages = [progress_stage(sample.progress) for sample in segment_samples]
            stage_votes: dict[str, float] = {}
            view_results: list[tuple[EvidenceFrame, str, float]] = []
            for view in evidence_views:
                target_feature = load_feature(
                    view.object_key,
                    temp_dir,
                    camera_x=view.camera_x,
                    camera_y=view.camera_y,
                    heading_deg=view.heading_deg,
                    segment=segment,
                )
                stage, visual_confidence = visual_stage_predict(
                    train_features, train_stages, target_feature
                )
                # A nearby camera is not proof that a beam is visible. Reject the
                # crop unless its pixels resemble labelled beam-stage evidence.
                if visual_confidence < MIN_VISUAL_MATCH_CONFIDENCE:
                    continue
                combined_confidence = visual_confidence * view.view_confidence
                stage_votes[stage] = stage_votes.get(stage, 0.0) + combined_confidence
                view_results.append((view, stage, combined_confidence))

            if not view_results:
                predictions.append(
                    BeamProgressPrediction(
                        project_id=project_id,
                        capture_id=capture.id,
                        beam_segment_id=segment.id,
                        evidence_keyframe_id=None,
                        progress_percent=None,
                        status="NOT_VISIBLE",
                        confidence=Decimal("0"),
                        needs_review=True,
                        model_version=MODEL_VERSION,
                        dataset_fingerprint=fingerprint,
                        training_sample_count=len(segment_samples),
                        inference_ms=0,
                    )
                )
                continue

            detected_stage, winning_vote = max(
                stage_votes.items(), key=lambda item: item[1]
            )
            agreement = winning_vote / max(sum(stage_votes.values()), 1e-6)
            supporting = [item for item in view_results if item[1] == detected_stage]
            mean_view_confidence = float(np.mean([item[2] for item in supporting]))
            confidence = max(
                0.0, min(1.0, 0.45 * agreement + 0.55 * mean_view_confidence)
            )
            needs_review = confidence < 0.60 or len(supporting) < 2
            best_evidence = max(view_results, key=lambda item: item[2])[0]
            progress = None if needs_review else STAGE_PROGRESS[detected_stage]
            status = "NEEDS_REVIEW" if needs_review else detected_stage
            predictions.append(
                BeamProgressPrediction(
                    project_id=project_id,
                    capture_id=capture.id,
                    beam_segment_id=segment.id,
                    evidence_keyframe_id=best_evidence.keyframe_id,
                    progress_percent=(
                        Decimal(str(round(progress, 3))) if progress is not None else None
                    ),
                    status=status,
                    confidence=Decimal(str(round(confidence, 5))),
                    needs_review=needs_review,
                    model_version=MODEL_VERSION,
                    dataset_fingerprint=fingerprint,
                    training_sample_count=len(segment_samples),
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
