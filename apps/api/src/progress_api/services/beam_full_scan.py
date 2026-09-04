from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from progress_api.services.beam_visual_detector import BeamDetection, BeamDetector
from progress_api.services.spherical_scan import SphericalView, render_spherical_views

FULL_SCAN_INTERVAL_MS = 2_000
DETECTOR_BATCH_SIZE = 4
MIN_DISTINCT_TIMESTAMPS = 3


@dataclass(frozen=True)
class PanoramaFrame:
    keyframe_id: uuid.UUID
    timestamp_ms: int
    image: np.ndarray
    camera_x: float | None = None
    camera_y: float | None = None
    heading_deg: float | None = None


@dataclass(frozen=True)
class BeamVisualEvidence:
    keyframe_id: uuid.UUID
    timestamp_ms: int
    yaw_deg: float
    pitch_deg: float
    stage: str
    score: float
    box_xyxy: tuple[float, float, float, float]
    camera_x: float | None
    camera_y: float | None
    global_bearing_deg: float | None


def select_full_timeline(
    frames: Sequence[PanoramaFrame], interval_ms: int = FULL_SCAN_INTERVAL_MS
) -> list[PanoramaFrame]:
    """Cover the complete video while avoiding thousands of near-identical frames."""
    ordered = sorted(frames, key=lambda frame: frame.timestamp_ms)
    if not ordered:
        return []
    selected = [ordered[0]]
    next_timestamp = ordered[0].timestamp_ms + interval_ms
    for frame in ordered[1:]:
        if frame.timestamp_ms >= next_timestamp:
            selected.append(frame)
            next_timestamp = frame.timestamp_ms + interval_ms
    if selected[-1].keyframe_id != ordered[-1].keyframe_id:
        selected.append(ordered[-1])
    return selected


def _horizontal_offset_deg(detection: BeamDetection, view: SphericalView) -> float:
    width = float(view.image.shape[1])
    center_x = (detection.box_xyxy[0] + detection.box_xyxy[2]) / 2
    return ((center_x / width) - 0.5) * view.fov_deg


def scan_panoramas(
    frames: Sequence[PanoramaFrame],
    detector: BeamDetector,
    *,
    interval_ms: int = FULL_SCAN_INTERVAL_MS,
    batch_size: int = DETECTOR_BATCH_SIZE,
) -> list[BeamVisualEvidence]:
    """Scan all times and all 24 directions; retain only detected beam evidence."""
    evidence: list[BeamVisualEvidence] = []
    pending: list[tuple[PanoramaFrame, SphericalView]] = []

    def flush() -> None:
        if not pending:
            return
        results = detector.detect([view.image for _frame, view in pending])
        if len(results) != len(pending):
            raise RuntimeError("ตัวตรวจคานคืนจำนวนผลลัพธ์ไม่ตรงกับจำนวนภาพ")
        for (frame, view), detections in zip(pending, results, strict=True):
            for detection in detections:
                global_bearing = None
                if frame.heading_deg is not None:
                    global_bearing = (
                        frame.heading_deg
                        + view.yaw_deg
                        + _horizontal_offset_deg(detection, view)
                    ) % 360.0
                evidence.append(
                    BeamVisualEvidence(
                        keyframe_id=frame.keyframe_id,
                        timestamp_ms=frame.timestamp_ms,
                        yaw_deg=view.yaw_deg,
                        pitch_deg=view.pitch_deg,
                        stage=detection.stage,
                        score=detection.score,
                        box_xyxy=detection.box_xyxy,
                        camera_x=frame.camera_x,
                        camera_y=frame.camera_y,
                        global_bearing_deg=global_bearing,
                    )
                )
        pending.clear()

    for frame in select_full_timeline(frames, interval_ms):
        for view in render_spherical_views(frame.image):
            pending.append((frame, view))
            if len(pending) >= batch_size:
                flush()
    flush()
    return evidence


def angular_distance_deg(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def evidence_for_plan_segment(
    evidence: Iterable[BeamVisualEvidence],
    *,
    segment_midpoint: tuple[float, float],
    max_plan_distance: float,
    max_bearing_error_deg: float = 35.0,
) -> list[BeamVisualEvidence]:
    """Associate detections using camera proximity and observed viewing bearing."""
    midpoint_x, midpoint_y = segment_midpoint
    matches: list[BeamVisualEvidence] = []
    for item in evidence:
        if (
            item.camera_x is None
            or item.camera_y is None
            or item.global_bearing_deg is None
        ):
            continue
        distance = math.hypot(item.camera_x - midpoint_x, item.camera_y - midpoint_y)
        if distance > max_plan_distance:
            continue
        expected = (
            math.degrees(
                math.atan2(midpoint_x - item.camera_x, -(midpoint_y - item.camera_y))
            )
            + 360.0
        ) % 360.0
        if angular_distance_deg(item.global_bearing_deg, expected) <= max_bearing_error_deg:
            matches.append(item)
    return matches


def observed_stage(
    evidence: Iterable[BeamVisualEvidence],
) -> tuple[str | None, float, int]:
    """Vote from real detections only; never infer from dates or missing objects."""
    best_by_stage_and_time: dict[tuple[str, int], float] = {}
    for item in evidence:
        key = (item.stage, item.timestamp_ms)
        best_by_stage_and_time[key] = max(best_by_stage_and_time.get(key, 0.0), item.score)
    votes: dict[str, list[float]] = {}
    for (stage, _timestamp), score in best_by_stage_and_time.items():
        votes.setdefault(stage, []).append(score)
    eligible = {
        stage: scores
        for stage, scores in votes.items()
        if len(scores) >= MIN_DISTINCT_TIMESTAMPS
    }
    if not eligible:
        return None, 0.0, 0
    stage, scores = max(
        eligible.items(), key=lambda item: (sum(item[1]), len(item[1]))
    )
    confidence = min(1.0, float(np.mean(scores)) * min(1.0, len(scores) / 5.0))
    return stage, confidence, len(scores)
