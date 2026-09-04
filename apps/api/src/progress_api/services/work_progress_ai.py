from __future__ import annotations

import hashlib
import time
import uuid
from decimal import Decimal
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from progress_api.models import (
    Capture,
    FloorWorkItem,
    Keyframe,
    MediaFile,
    WorkProgressEntry,
    WorkProgressPrediction,
)
from progress_api.object_storage import download_object
from progress_api.services.beam_progress_ai import (
    MIN_DEVELOPMENT_DATES,
    extract_visual_feature,
    temporal_progress_predict,
    visual_knn_predict,
)
from progress_api.services.temporary_workspace import temporary_workspace

MODEL_VERSION = "floor-work-visual-temporal-v1"


def _latest_labels(db: Session, project_id: uuid.UUID, target_capture_id: uuid.UUID):
    rows = db.execute(
        select(WorkProgressEntry, Capture, Keyframe, MediaFile)
        .join(Capture, Capture.id == WorkProgressEntry.capture_id)
        .join(Keyframe, Keyframe.id == WorkProgressEntry.evidence_keyframe_id)
        .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
        .where(
            WorkProgressEntry.project_id == project_id,
            WorkProgressEntry.capture_id != target_capture_id,
            Capture.dataset_split == "DEVELOPMENT",
            Keyframe.quality_status == "USABLE",
        )
        .order_by(WorkProgressEntry.created_at.desc())
    ).all()
    latest = {}
    for entry, capture, keyframe, media in rows:
        latest.setdefault((capture.id, entry.work_item_id), (entry, capture, keyframe, media))
    return list(latest.values())


def _target_frames(db: Session, capture_id: uuid.UUID) -> list[tuple[Keyframe, MediaFile]]:
    return list(db.execute(
        select(Keyframe, MediaFile)
        .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
        .where(Keyframe.capture_id == capture_id, Keyframe.quality_status == "USABLE")
        .order_by(Keyframe.timestamp_ms)
    ).all())


def run_work_progress_inference(
    db: Session,
    *,
    project_id: uuid.UUID,
    capture: Capture,
    items: list[FloorWorkItem],
) -> list[WorkProgressPrediction]:
    started = time.perf_counter()
    labels = _latest_labels(db, project_id, capture.id)
    target_frames = _target_frames(db, capture.id)
    if not target_frames:
        raise ValueError("Capture นี้ยังไม่มี Keyframe ที่ใช้งานได้")
    fingerprint_payload = "|".join(sorted(
        f"{entry.capture_id}:{entry.work_item_id}:{entry.evidence_keyframe_id}:{entry.progress_percent}"
        for entry, _capture, _keyframe, _media in labels
    ))
    fingerprint = hashlib.sha256(fingerprint_payload.encode()).hexdigest()
    cache: dict[str, np.ndarray] = {}

    def feature(object_key: str, temp_dir: Path) -> np.ndarray:
        if object_key not in cache:
            destination = temp_dir / f"{hashlib.sha1(object_key.encode()).hexdigest()}.jpg"
            download_object(key=object_key, destination=str(destination))
            image = cv2.imread(str(destination), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"อ่านภาพหลักฐานไม่ได้: {object_key}")
            cache[object_key] = extract_visual_feature(image)
        return cache[object_key]

    predictions: list[WorkProgressPrediction] = []
    with temporary_workspace(prefix="floor-work-progress-") as directory:
        temp_dir = Path(directory)
        for item in items:
            samples = [row for row in labels if row[0].work_item_id == item.id]
            sample_dates = {row[1].captured_at.date() for row in samples}
            # Spread work packages over the available 360 evidence instead of relying
            # on the currently deferred floor-plan alignment.
            frame_index = (
                int(hashlib.sha1(item.code.encode()).hexdigest()[:8], 16)
                % len(target_frames)
            )
            evidence_keyframe, evidence_media = target_frames[frame_index]
            if len(sample_dates) < MIN_DEVELOPMENT_DATES:
                prediction = WorkProgressPrediction(
                    project_id=project_id, capture_id=capture.id, work_item_id=item.id,
                    evidence_keyframe_id=evidence_keyframe.id, progress_percent=None,
                    status="NOT_TRAINED", confidence=Decimal("0"), needs_review=True,
                    model_version=MODEL_VERSION, dataset_fingerprint=fingerprint,
                    training_sample_count=len(samples), inference_ms=0,
                )
            else:
                train_features = np.stack([feature(row[3].object_key, temp_dir) for row in samples])
                targets = np.asarray(
                    [float(row[0].progress_percent) for row in samples],
                    dtype=np.float32,
                )
                visual, visual_confidence = visual_knn_predict(
                    train_features, targets, feature(evidence_media.object_key, temp_dir)
                )
                temporal, temporal_confidence = temporal_progress_predict(
                    [row[1].captured_at.isoformat() for row in samples], targets,
                    capture.captured_at.isoformat(),
                )
                value = max(0.0, min(100.0, 0.55 * visual + 0.45 * temporal))
                confidence = max(0.0, min(1.0, 0.6 * visual_confidence + 0.4 * temporal_confidence))
                status = "INSTALLED" if value >= 95 else "NOT_STARTED" if value <= 5 else "PARTIAL"
                prediction = WorkProgressPrediction(
                    project_id=project_id, capture_id=capture.id, work_item_id=item.id,
                    evidence_keyframe_id=evidence_keyframe.id,
                    progress_percent=Decimal(str(round(value, 3))), status=status,
                    confidence=Decimal(str(round(confidence, 5))), needs_review=confidence < 0.60,
                    model_version=MODEL_VERSION, dataset_fingerprint=fingerprint,
                    training_sample_count=len(samples), inference_ms=0,
                )
            predictions.append(prediction)
    elapsed = max(1, round((time.perf_counter() - started) * 1000))
    for prediction in predictions:
        prediction.inference_ms = max(1, elapsed // max(len(predictions), 1))
        db.add(prediction)
    db.commit()
    return predictions
