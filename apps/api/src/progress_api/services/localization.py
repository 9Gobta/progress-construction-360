from __future__ import annotations

import hashlib
import logging
import math
import shutil
import subprocess
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from progress_api.config import get_settings
from progress_api.models import (
    CameraPose,
    Capture,
    CapturePathPoint,
    Keyframe,
    MediaFile,
    PathControlPoint,
    PathEvaluationPoint,
    ProcessingJob,
)
from progress_api.models.base import utc_now
from progress_api.object_storage import download_media_file, download_object, upload_file
from progress_api.services.learned_relocalization import (
    LearnedRelocalizationUnavailable,
    learned_3d_plan_anchors,
    learned_panorama_matches,
)
from progress_api.services.sfm_localization import SfMPathSample, recover_sfm_path
from progress_api.services.stella_localization import (
    StellaLocalizationError,
    recover_stella_path,
)
from progress_api.services.temporary_workspace import temporary_workspace

LOCALIZATION_FPS = 1
LOCALIZATION_WIDTH = 960
LOCALIZATION_HEIGHT = 480
STELLA_ALGORITHM_VERSION = "stella-vslam-visual-graph-v4"
RIG_SFM_ALGORITHM_VERSION = "rig-pycolmap-panorama-sfm-v1"
FLOOR_ONE_PLAN_BOUNDS = (0.18, 0.70, 0.22, 0.76)
PRIOR_MATCH_INTERVAL_SECONDS = 2
PRIOR_MATCH_LIMIT = 48
PRIOR_MIN_FEATURE_INLIERS = 16
PRIOR_MIN_ROUTE_MATCHES = 5
PRIOR_MAX_PLAN_RESIDUAL = 0.075
PRIOR_MIN_PLAN_AXIS_SPAN = 0.08
PRIOR_MAX_AFFINE_ANISOTROPY = 2.5
ANCHOR_LIBRARY_LIMIT = 72
ANCHOR_LIBRARY_CAPTURE_LIMIT = 8
ANCHOR_PLAN_CLUSTER_SIZE = 0.035
PERSISTENT_MAP_MIN_CONTROL_POINTS = 3
PERSISTENT_MAP_AUTO_ACCEPT_CONFIDENCE = 0.80
PERSISTENT_MAP_MAX_START_ERROR = 0.12
LEARNED_CHAIN_AUTO_ACCEPT_CONFIDENCE = 0.88
LEARNED_3D_AUTO_ACCEPT_CONFIDENCE = 0.88

logger = logging.getLogger(__name__)


def _visual_algorithm_version() -> str:
    return (
        RIG_SFM_ALGORITHM_VERSION
        if get_settings().localization_engine == "pycolmap"
        else STELLA_ALGORITHM_VERSION
    )


def _alignment_is_auto_accepted(alignment: PlanAlignment) -> bool:
    """Return whether an absolute plan alignment is safe to publish.

    Legacy ORB and geometric plan-fit results are intentionally excluded even
    when their internal score is high. Only Stella localization against a
    trusted map or the learned cross-capture chain may clear review by itself.
    """
    if alignment.source.startswith("persistent-map-v1:"):
        return alignment.confidence >= PERSISTENT_MAP_AUTO_ACCEPT_CONFIDENCE
    if alignment.source.startswith(("previous-hloc-sfm-v1:", "previous-hloc-6dof-v2:")):
        return alignment.confidence >= LEARNED_3D_AUTO_ACCEPT_CONFIDENCE
    return False


class LocalizationError(RuntimeError):
    pass


def recover_visual_path(
    source: Path,
    *,
    end_timestamp_ms: int,
    map_db_input: Path | None = None,
    map_db_output: Path | None = None,
    spatial_model_output: Path | None = None,
) -> list[SfMPathSample]:
    """Run the configured engine; never silently substitute a synthetic path."""
    engine = get_settings().localization_engine
    if engine == "stella_vslam":
        return recover_stella_path(
            source,
            end_timestamp_ms=end_timestamp_ms,
            map_db_input=map_db_input,
            map_db_output=map_db_output,
        )
    if engine == "pycolmap":
        return recover_sfm_path(
            source,
            end_timestamp_ms=end_timestamp_ms,
            spatial_model_output=spatial_model_output,
        )
    raise LocalizationError(f"Unsupported localization engine: {engine}")


@dataclass(frozen=True)
class Motion:
    step: float
    yaw_delta_deg: float
    confidence: float


@dataclass(frozen=True)
class EstimatedPose:
    x: float
    y: float
    heading_deg: float
    confidence: float
    relative_z: float = 0.0


@dataclass(frozen=True)
class EstimatedPathPoint:
    timestamp_ms: int
    pose: EstimatedPose


@dataclass(frozen=True)
class PlanAlignment:
    points: list[tuple[float, float, float]]
    scale: float
    rotation_deg: float
    mirror: bool
    confidence: float
    source: str
    spatial_samples: list[SfMPathSample] | None = None
    spatial_camera_height: float | None = None


@dataclass(frozen=True)
class PersistentMapReference:
    map_capture_id: uuid.UUID
    calibration_capture_id: uuid.UUID
    object_key: str
    start_x: float
    start_y: float


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise LocalizationError("ไม่พบ ffmpeg ใน PATH")
    return path


def _extract_tracking_frames(source: Path, output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    command = [
        _ffmpeg(),
        "-y",
        "-i",
        str(source),
        "-vf",
        f"fps={LOCALIZATION_FPS},scale={LOCALIZATION_WIDTH}:{LOCALIZATION_HEIGHT}",
        "-q:v",
        "4",
        str(output / "%06d.jpg"),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        raise LocalizationError((exc.stderr or str(exc))[-3000:]) from exc
    frames = sorted(output.glob("*.jpg"))
    if len(frames) < 2:
        raise LocalizationError("วิดีโอสั้นเกินไปสำหรับประมาณเส้นทาง")
    return frames


def _motion_between(previous: np.ndarray, current: np.ndarray) -> Motion:
    orb = cv2.ORB_create(nfeatures=1800, scaleFactor=1.2, nlevels=8)
    previous_points, previous_descriptors = orb.detectAndCompute(previous, None)
    current_points, current_descriptors = orb.detectAndCompute(current, None)
    if previous_descriptors is None or current_descriptors is None:
        return Motion(step=0.0015, yaw_delta_deg=0.0, confidence=0.10)

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(
        matcher.match(previous_descriptors, current_descriptors),
        key=lambda match: match.distance,
    )[:250]
    if len(matches) < 12:
        return Motion(step=0.0015, yaw_delta_deg=0.0, confidence=0.12)

    source = np.float32([previous_points[item.queryIdx].pt for item in matches])
    target = np.float32([current_points[item.trainIdx].pt for item in matches])
    transform, inlier_mask = cv2.estimateAffinePartial2D(
        source,
        target,
        method=cv2.RANSAC,
        ransacReprojThreshold=3.0,
        maxIters=2000,
        confidence=0.99,
    )
    if transform is None or inlier_mask is None:
        return Motion(step=0.002, yaw_delta_deg=0.0, confidence=0.15)

    inliers = inlier_mask.ravel().astype(bool)
    inlier_count = int(inliers.sum())
    if inlier_count < 8:
        return Motion(step=0.002, yaw_delta_deg=0.0, confidence=0.18)

    displacement = target[inliers] - source[inliers]
    median_dx = float(np.median(displacement[:, 0]))
    median_distance = float(np.median(np.linalg.norm(displacement, axis=1)))
    inlier_ratio = inlier_count / len(matches)
    match_score = min(1.0, inlier_count / 80.0)
    confidence = max(0.10, min(0.92, 0.65 * inlier_ratio + 0.35 * match_score))

    # Horizontal displacement in an equirectangular frame approximates camera yaw.
    yaw_delta = max(-32.0, min(32.0, -(median_dx / previous.shape[1]) * 360.0))
    normalized_motion = min(1.0, median_distance / 28.0)
    step = (0.0025 + 0.0075 * normalized_motion) * (0.45 + 0.55 * confidence)
    return Motion(step=step, yaw_delta_deg=yaw_delta, confidence=confidence)


def _relative_path(frames: list[Path]) -> tuple[list[tuple[float, float, float]], list[float]]:
    first = cv2.imread(str(frames[0]), cv2.IMREAD_GRAYSCALE)
    if first is None:
        raise LocalizationError("อ่าน Tracking frame แรกไม่ได้")
    points = [(0.0, 0.0, 0.0)]
    confidences = [1.0]
    previous = first
    x = y = heading = 0.0
    for frame in frames[1:]:
        current = cv2.imread(str(frame), cv2.IMREAD_GRAYSCALE)
        if current is None:
            points.append((x, y, heading))
            confidences.append(0.05)
            continue
        motion = _motion_between(previous, current)
        heading = (heading + motion.yaw_delta_deg) % 360.0
        angle = math.radians(heading)
        x += math.cos(angle) * motion.step
        y += math.sin(angle) * motion.step
        points.append((x, y, heading))
        confidences.append(motion.confidence)
        previous = current
    return points, confidences


def _fit_to_plan(
    relative: list[tuple[float, float, float]],
    start_x: float,
    start_y: float,
    bounds: tuple[float, float, float, float] = (0.025, 0.975, 0.025, 0.975),
) -> tuple[list[tuple[float, float, float]], float]:
    min_x, max_x, min_y, max_y = bounds
    best_score = float("inf")
    best_angle = 0.0
    best_scale = 1.0
    relative_x = [point[0] for point in relative]
    relative_y = [point[1] for point in relative]
    path_span = max(max(relative_x) - min(relative_x), max(relative_y) - min(relative_y))
    available_span = min(max_x - min_x, max_y - min_y)
    largest_scale = min(1.0, (available_span * 0.92) / max(path_span, 1e-6))
    scale_candidates = np.linspace(largest_scale, largest_scale * 0.20, 21)

    for initial_heading in range(0, 360, 5):
        rotation = math.radians(initial_heading)
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        for scale in scale_candidates:
            score = 0.0
            for rel_x, rel_y, _ in relative:
                x = start_x + scale * (rel_x * cos_r - rel_y * sin_r)
                y = start_y + scale * (rel_x * sin_r + rel_y * cos_r)
                outside_x = max(0.0, min_x - x, x - max_x)
                outside_y = max(0.0, min_y - y, y - max_y)
                score += 5000.0 * (outside_x**2 + outside_y**2)
                edge = min(x - min_x, y - min_y, max_x - x, max_y - y)
                if edge < 0.02:
                    score += (0.02 - edge) * 2.0
            score += (largest_scale - float(scale)) * 0.03
            if score < best_score:
                best_score = score
                best_angle = float(initial_heading)
                best_scale = float(scale)

    rotation = math.radians(best_angle)
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    fitted: list[tuple[float, float, float]] = []
    for rel_x, rel_y, rel_heading in relative:
        x = start_x + best_scale * (rel_x * cos_r - rel_y * sin_r)
        y = start_y + best_scale * (rel_x * sin_r + rel_y * cos_r)
        fitted.append(
            (
                min(max_x, max(min_x, x)),
                min(max_y, max(min_y, y)),
                (rel_heading + best_angle) % 360.0,
            )
        )
    return fitted, best_scale


def _fit_to_grid_six_road_edge(
    relative: list[tuple[float, float, float]],
    start_x: float,
    start_y: float,
    bounds: tuple[float, float, float, float] = FLOOR_ONE_PLAN_BOUNDS,
) -> tuple[list[tuple[float, float, float]], float, float]:
    """Fit a Stella route using the surveyed Grid 6 road-side orientation.

    At this project Grid 6 (A-D) is the road-facing, vertical edge on the
    normalized plan.  The capture starts at that edge.  Monocular SLAM has no
    absolute compass heading, so use the first meaningful movement vector and
    consider only the two directions parallel to Grid 6.  The direction that
    remains inside the building footprint wins.  This removes the arbitrary
    360-degree rotation search while preserving Stella's connected geometry.
    """
    if len(relative) < 2:
        fitted, scale = _fit_to_plan(relative, start_x, start_y, bounds)
        return fitted, scale, 0.0

    first_x, first_y, _ = relative[0]
    span = max(
        max(point[0] for point in relative) - min(point[0] for point in relative),
        max(point[1] for point in relative) - min(point[1] for point in relative),
        1e-6,
    )
    movement = next(
        (
            (x - first_x, y - first_y)
            for x, y, _ in relative[1:]
            if math.hypot(x - first_x, y - first_y) >= span * 0.08
        ),
        (relative[-1][0] - first_x, relative[-1][1] - first_y),
    )
    movement_angle = math.degrees(math.atan2(movement[1], movement[0]))
    min_x, max_x, min_y, max_y = bounds
    path_span = max(
        max(point[0] for point in relative) - min(point[0] for point in relative),
        max(point[1] for point in relative) - min(point[1] for point in relative),
    )
    available_span = min(max_x - min_x, max_y - min_y)
    largest_scale = min(1.0, (available_span * 0.92) / max(path_span, 1e-6))

    best_score = float("inf")
    best_scale = largest_scale
    best_rotation = 0.0
    # In image coordinates, up the plan is -Y and down is +Y.  Starting near
    # Grid 6's lower end naturally selects the upward candidate.
    for target_heading in (-90.0, 90.0):
        rotation_deg = target_heading - movement_angle
        rotation = math.radians(rotation_deg)
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        for scale in np.linspace(largest_scale, largest_scale * 0.20, 31):
            score = 0.0
            for rel_x, rel_y, _ in relative:
                x = start_x + scale * (rel_x * cos_r - rel_y * sin_r)
                y = start_y + scale * (rel_x * sin_r + rel_y * cos_r)
                outside_x = max(0.0, min_x - x, x - max_x)
                outside_y = max(0.0, min_y - y, y - max_y)
                score += 10000.0 * (outside_x**2 + outside_y**2)
            # Prefer a useful large route and keep the first segment parallel
            # to the surveyed road edge rather than accepting a tiny cluster.
            score += (largest_scale - float(scale)) * 0.05
            if score < best_score:
                best_score = score
                best_scale = float(scale)
                best_rotation = rotation_deg

    rotation = math.radians(best_rotation)
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    fitted = [
        (
            min(max_x, max(min_x, start_x + best_scale * (x * cos_r - y * sin_r))),
            min(max_y, max(min_y, start_y + best_scale * (x * sin_r + y * cos_r))),
            (heading + best_rotation) % 360.0,
        )
        for x, y, heading in relative
    ]
    return fitted, best_scale, best_rotation


def _transform_with_fixed_start(
    relative: list[tuple[float, float, float]],
    *,
    start_x: float,
    start_y: float,
    scale: float,
    rotation_deg: float,
    mirror: bool = False,
) -> list[tuple[float, float, float]]:
    rotation = math.radians(rotation_deg)
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    transformed: list[tuple[float, float, float]] = []
    for x, y, heading in relative:
        # Stella's equirectangular yaw is atan2(forward X, forward Z): zero
        # therefore maps to the visual Y/Z axis. Positions use [x, y], so the
        # matching heading vector is [sin(yaw), cos(yaw)], not [cos, sin].
        direction_x = math.sin(math.radians(heading))
        direction_y = math.cos(math.radians(heading)) * (-1 if mirror else 1)
        plan_direction_x = direction_x * cos_r - direction_y * sin_r
        plan_direction_y = direction_x * sin_r + direction_y * cos_r
        transformed.append((
            min(
                1.0,
                max(
                    0.0,
                    start_x
                    + scale * (x * cos_r - (-y if mirror else y) * sin_r),
                ),
            ),
            min(
                1.0,
                max(
                    0.0,
                    start_y
                    + scale * (x * sin_r + (-y if mirror else y) * cos_r),
                ),
            ),
            math.degrees(math.atan2(plan_direction_y, plan_direction_x)) % 360.0,
        ))
    return transformed


def _estimate_prior_similarity(
    correspondences: list[tuple[tuple[float, float], tuple[float, float]]],
    *,
    start_x: float,
    start_y: float,
) -> tuple[float, float, bool, float, int] | None:
    """Estimate reflection/rotation/scale while keeping the selected start fixed."""
    raw_usable = [
        (complex(source_x, source_y), complex(target_x - start_x, target_y - start_y))
        for (source_x, source_y), (target_x, target_y) in correspondences
        if math.hypot(source_x, source_y) > 1e-5
    ]
    if len(raw_usable) < 2:
        return None

    best_inliers: list[tuple[complex, complex]] = []
    best_residual = float("inf")
    best_factor = 0j
    best_mirror = False
    for mirror in (False, True):
        usable = [
            (source.conjugate() if mirror else source, target)
            for source, target in raw_usable
        ]
        for source, target in usable:
            factor = target / source
            scale = abs(factor)
            if not 0.002 <= scale <= 20.0:
                continue
            residuals = [
                (abs(factor * item_source - item_target), item_source, item_target)
                for item_source, item_target in usable
            ]
            inliers = [
                (item_source, item_target)
                for residual, item_source, item_target in residuals
                if residual <= PRIOR_MAX_PLAN_RESIDUAL
            ]
            if len(inliers) < 2:
                continue
            median_residual = float(
                np.median(
                    [
                        abs(factor * item_source - item_target)
                        for item_source, item_target in inliers
                    ]
                )
            )
            if len(inliers) > len(best_inliers) or (
                len(inliers) == len(best_inliers) and median_residual < best_residual
            ):
                best_inliers = inliers
                best_residual = median_residual
                best_factor = factor
                best_mirror = mirror

    if len(best_inliers) < 2:
        return None
    denominator = sum(abs(source) ** 2 for source, _target in best_inliers)
    if denominator <= 1e-9:
        return None
    best_factor = (
        sum(source.conjugate() * target for source, target in best_inliers)
        / denominator
    )
    residual = float(
        np.median(
            [abs(best_factor * source - target) for source, target in best_inliers]
        )
    )
    confidence = max(
        0.0,
        min(0.98, 0.48 + 0.09 * len(best_inliers) - 4.0 * residual),
    )
    rotation_deg = math.degrees(math.atan2(best_factor.imag, best_factor.real))
    return abs(best_factor), rotation_deg, best_mirror, confidence, len(best_inliers)


def _estimate_prior_affine(
    correspondences: list[tuple[tuple[float, float], tuple[float, float]]],
    *,
    start_x: float,
    start_y: float,
) -> tuple[np.ndarray, float, list[int]] | None:
    """Fit a start-anchored 2D transform with independent X/Y scale using RANSAC."""
    usable = [
        (index, (source_x, source_y), (target_x - start_x, target_y - start_y))
        for index, ((source_x, source_y), (target_x, target_y)) in enumerate(
            correspondences
        )
        if math.hypot(source_x, source_y) > 1e-5
    ]
    if len(usable) < 3:
        return None
    original_indices = [index for index, _source, _target in usable]
    sources = np.asarray(
        [source for _index, source, _target in usable], dtype=np.float64
    )
    targets = np.asarray(
        [target for _index, _source, target in usable], dtype=np.float64
    )
    # Independent-axis affine fitting becomes unstable when all matched plan
    # positions occupy one narrow strip. Fall back to the shape-preserving
    # similarity model rather than flattening the whole route onto that strip.
    target_span = np.ptp(targets, axis=0)
    if float(np.min(target_span)) < PRIOR_MIN_PLAN_AXIS_SPAN:
        return None
    best_indices: np.ndarray | None = None
    best_residual = float("inf")
    for first in range(len(usable) - 1):
        for second in range(first + 1, len(usable)):
            pair = sources[[first, second]]
            if abs(float(np.linalg.det(pair))) <= 1e-8:
                continue
            matrix = np.linalg.solve(pair, targets[[first, second]])
            singular_values = np.linalg.svd(matrix, compute_uv=False)
            if (
                singular_values[-1] < 0.002
                or singular_values[0] > 20.0
                or singular_values[0] / singular_values[-1] > PRIOR_MAX_AFFINE_ANISOTROPY
            ):
                continue
            residuals = np.linalg.norm(sources @ matrix - targets, axis=1)
            indices = np.flatnonzero(residuals <= PRIOR_MAX_PLAN_RESIDUAL)
            if len(indices) < 3:
                continue
            median_residual = float(np.median(residuals[indices]))
            if best_indices is None or len(indices) > len(best_indices) or (
                len(indices) == len(best_indices) and median_residual < best_residual
            ):
                best_indices = indices
                best_residual = median_residual
    if best_indices is None:
        return None
    matrix, _residuals, _rank, _singular = np.linalg.lstsq(
        sources[best_indices], targets[best_indices], rcond=None
    )
    residual = float(
        np.median(
            np.linalg.norm(
                sources[best_indices] @ matrix - targets[best_indices], axis=1
            )
        )
    )
    confidence = max(
        0.0,
        min(0.98, 0.45 + 0.08 * len(best_indices) - 4.0 * residual),
    )
    return matrix, confidence, [original_indices[int(index)] for index in best_indices]


def interpolate_piecewise_offsets(
    timestamps_ms: list[int],
    anchors: list[tuple[int, float, float]],
    *,
    max_offset: float = 0.15,
) -> list[tuple[float, float]]:
    """Interpolate bounded drift offsets while pinning the route origin."""
    grouped: dict[int, list[tuple[float, float]]] = {0: [(0.0, 0.0)]}
    for timestamp_ms, offset_x, offset_y in anchors:
        magnitude = math.hypot(offset_x, offset_y)
        if magnitude > max_offset and magnitude > 0:
            ratio = max_offset / magnitude
            offset_x *= ratio
            offset_y *= ratio
        grouped.setdefault(max(0, timestamp_ms), []).append((offset_x, offset_y))
    anchor_times = sorted(grouped)
    anchor_x = [
        float(np.median([value[0] for value in grouped[item]]))
        for item in anchor_times
    ]
    anchor_y = [
        float(np.median([value[1] for value in grouped[item]]))
        for item in anchor_times
    ]
    return [
        (
            float(np.interp(timestamp, anchor_times, anchor_x)),
            float(np.interp(timestamp, anchor_times, anchor_y)),
        )
        for timestamp in timestamps_ms
    ]


def _anchor_constrained_alignment(
    relative_samples: list[SfMPathSample],
    correspondences: list[tuple[tuple[float, float], tuple[float, float]]],
    correspondence_timestamps: list[int],
    *,
    start_x: float,
    start_y: float,
    source_label: str,
) -> PlanAlignment | None:
    """Place a Stella track with labelled camera positions while pinning t=0.

    The global affine/similarity transform preserves the route as one connected
    track.  Residual drift is then corrected between verified observations in
    timestamp order; the implicit zero-offset anchor at t=0 keeps the selected
    start position exact.
    """
    if len(correspondences) != len(correspondence_timestamps):
        raise ValueError("Anchor coordinates and timestamps must have equal length")
    relative = [(sample.x, sample.y, sample.heading_deg) for sample in relative_samples]
    affine = _estimate_prior_affine(
        correspondences,
        start_x=start_x,
        start_y=start_y,
    )
    if affine is not None:
        matrix, confidence, inlier_indices = affine
        singular_values = np.linalg.svd(matrix, compute_uv=False)
        scale = float(np.mean(singular_values))
        rotation_deg = math.degrees(math.atan2(matrix[0, 1], matrix[0, 0]))
        mirror = float(np.linalg.det(matrix)) < 0
        points = _transform_with_fixed_start_affine(
            relative,
            start_x=start_x,
            start_y=start_y,
            matrix=matrix,
        )
        drift_anchors: list[tuple[int, float, float]] = []
        for index in inlier_indices:
            (source_x, source_y), (target_x, target_y) = correspondences[index]
            predicted_delta = np.asarray([source_x, source_y]) @ matrix
            drift_anchors.append(
                (
                    correspondence_timestamps[index],
                    target_x - (start_x + float(predicted_delta[0])),
                    target_y - (start_y + float(predicted_delta[1])),
                )
            )
        piecewise_suffix = ""
        if len({item[0] for item in drift_anchors}) >= 3:
            offsets = interpolate_piecewise_offsets(
                [sample.timestamp_ms for sample in relative_samples],
                drift_anchors,
                max_offset=0.10,
            )
            points = [
                (
                    min(1.0, max(0.0, x + offset_x)),
                    min(1.0, max(0.0, y + offset_y)),
                    heading,
                )
                for (x, y, heading), (offset_x, offset_y) in zip(
                    points, offsets, strict=True
                )
            ]
            piecewise_suffix = "-piecewise"
        return PlanAlignment(
            points=points,
            scale=scale,
            rotation_deg=rotation_deg,
            mirror=mirror,
            confidence=confidence,
            source=(
                f"{source_label}:{len(inlier_indices)}-anchors"
                f"{'-mirror' if mirror else ''}{piecewise_suffix}"
            ),
        )

    similarity = _estimate_prior_similarity(
        correspondences,
        start_x=start_x,
        start_y=start_y,
    )
    if similarity is None:
        return None
    scale, rotation_deg, mirror, confidence, inlier_count = similarity
    return PlanAlignment(
        points=_transform_with_fixed_start(
            relative,
            start_x=start_x,
            start_y=start_y,
            scale=scale,
            rotation_deg=rotation_deg,
            mirror=mirror,
        ),
        scale=scale,
        rotation_deg=rotation_deg,
        mirror=mirror,
        confidence=confidence,
        source=(
            f"{source_label}:{inlier_count}-anchors"
            f"{'-mirror' if mirror else ''}"
        ),
    )
def _transform_with_fixed_start_affine(
    relative: list[tuple[float, float, float]],
    *,
    start_x: float,
    start_y: float,
    matrix: np.ndarray,
) -> list[tuple[float, float, float]]:
    transformed: list[tuple[float, float, float]] = []
    for x, y, heading in relative:
        plan_delta = np.asarray([x, y]) @ matrix
        direction = np.asarray(
            [math.sin(math.radians(heading)), math.cos(math.radians(heading))]
        ) @ matrix
        plan_heading = math.degrees(math.atan2(direction[1], direction[0])) % 360.0
        transformed.append(
            (
                min(1.0, max(0.0, start_x + float(plan_delta[0]))),
                min(1.0, max(0.0, start_y + float(plan_delta[1]))),
                plan_heading,
            )
        )
    return transformed


def _read_orb_features(path: Path) -> tuple[list[cv2.KeyPoint], np.ndarray | None]:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return [], None
    image = cv2.resize(image, (960, 480), interpolation=cv2.INTER_AREA)
    orb = cv2.ORB_create(nfeatures=2200, scaleFactor=1.2, nlevels=8)
    return orb.detectAndCompute(image, None)


def _feature_match_inliers(
    first: tuple[list[cv2.KeyPoint], np.ndarray | None],
    second: tuple[list[cv2.KeyPoint], np.ndarray | None],
) -> int:
    first_points, first_descriptors = first
    second_points, second_descriptors = second
    if first_descriptors is None or second_descriptors is None:
        return 0
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(first_descriptors, second_descriptors, k=2)
    good = [
        pair[0]
        for pair in pairs
        if len(pair) == 2 and pair[0].distance < 0.72 * pair[1].distance
    ]
    if len(good) < PRIOR_MIN_FEATURE_INLIERS:
        return 0
    source = np.float32([first_points[item.queryIdx].pt for item in good])
    target = np.float32([second_points[item.trainIdx].pt for item in good])
    _homography, mask = cv2.findHomography(source, target, cv2.RANSAC, 4.0)
    return int(mask.sum()) if mask is not None else 0


def _select_unique_visual_matches(
    scored: list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    """Keep the strongest one-to-one current/reference image matches."""
    selected: list[tuple[int, int, int]] = []
    used_current: set[int] = set()
    used_previous: set[int] = set()
    for match in sorted(scored, reverse=True):
        _score, current_index, previous_index = match
        if current_index in used_current or previous_index in used_previous:
            continue
        selected.append(match)
        used_current.add(current_index)
        used_previous.add(previous_index)
    return selected


def _extract_prior_match_frames(source: Path, output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    command = [
        _ffmpeg(),
        "-y",
        "-v",
        "error",
        "-i",
        str(source),
        "-vf",
        f"fps=1/{PRIOR_MATCH_INTERVAL_SECONDS},scale=960:480",
        "-q:v",
        "4",
        str(output / "%05d.jpg"),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        raise LocalizationError((exc.stderr or str(exc))[-3000:]) from exc
    return sorted(output.glob("*.jpg"))


def _nearest_relative_point(
    relative_samples: list[SfMPathSample], timestamp_ms: int
) -> SfMPathSample:
    return min(relative_samples, key=lambda sample: abs(sample.timestamp_ms - timestamp_ms))


def _plan_cluster(x: float, y: float) -> tuple[int, int]:
    return (
        round(x / ANCHOR_PLAN_CLUSTER_SIZE),
        round(y / ANCHOR_PLAN_CLUSTER_SIZE),
    )


def _select_labelled_anchor_matches(
    current_features: list[tuple[list[cv2.KeyPoint], np.ndarray | None]],
    reference_features: list[tuple[list[cv2.KeyPoint], np.ndarray | None]],
    reference_positions: list[tuple[float, float]],
) -> list[tuple[int, int, int]]:
    """Match current panoramas to distinct human-labelled plan locations.

    Multiple historical captures near the same plan point vote as one spatial
    landmark. This prevents repeated columns/formwork from winning merely
    because one area has more labelled images than another.
    """
    candidates_by_cluster: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for current_index, current_feature in enumerate(current_features):
        cluster_scores: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for reference_index, reference_feature in enumerate(reference_features):
            score = _feature_match_inliers(current_feature, reference_feature)
            if score < PRIOR_MIN_FEATURE_INLIERS:
                continue
            cluster = _plan_cluster(*reference_positions[reference_index])
            cluster_scores.setdefault(cluster, []).append((score, reference_index))
        ranked: list[tuple[float, int, int, tuple[int, int]]] = []
        for cluster, values in cluster_scores.items():
            values.sort(reverse=True)
            best_score, best_reference = values[0]
            # A second date confirming the same location is useful evidence,
            # but must not let densely labelled areas dominate the route.
            vote = float(best_score)
            if len(values) > 1:
                vote += 0.25 * values[1][0]
            ranked.append((vote, best_score, best_reference, cluster))
        ranked.sort(reverse=True)
        if not ranked:
            continue
        best_vote, best_score, best_reference, best_cluster = ranked[0]
        second_vote = ranked[1][0] if len(ranked) > 1 else 0.0
        if second_vote >= PRIOR_MIN_FEATURE_INLIERS and best_vote < second_vote * 1.15:
            continue
        candidates_by_cluster.setdefault(best_cluster, []).append(
            (best_score, current_index, best_reference)
        )

    # One strong observation per physical plan area is enough to fit the
    # global transform and avoids bending the track toward duplicate anchors.
    selected = [max(values) for values in candidates_by_cluster.values()]
    return sorted(selected, key=lambda item: item[1])


def _select_scored_labelled_anchor_matches(
    scored: list[tuple[int, int, int]],
    reference_positions: list[tuple[float, float]],
) -> list[tuple[int, int, int]]:
    """Keep strong one-to-one learned matches for geometric route fitting.

    The final route transform is estimated with RANSAC below, so discarding all
    but one observation per plan cluster here removes useful evidence and can
    make a good chronological match fail.  We only remove ambiguous queries
    and duplicate current/reference panoramas at this stage.  RANSAC then
    rejects geometrically inconsistent repetitive bays as outliers.
    """
    by_current: dict[int, list[tuple[int, int]]] = {}
    for score, current_index, reference_index in scored:
        by_current.setdefault(current_index, []).append((score, reference_index))

    unambiguous: list[tuple[int, int, int]] = []
    for current_index, candidates in by_current.items():
        by_cluster: dict[tuple[int, int], tuple[int, int]] = {}
        for score, reference_index in candidates:
            cluster = _plan_cluster(*reference_positions[reference_index])
            if cluster not in by_cluster or score > by_cluster[cluster][0]:
                by_cluster[cluster] = (score, reference_index)
        ranked = sorted(
            (
                (score, reference_index, cluster)
                for cluster, (score, reference_index) in by_cluster.items()
            ),
            reverse=True,
        )
        if not ranked:
            continue
        best_score, best_reference, best_cluster = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0
        # Construction interiors contain many visually identical bays. A match
        # is useful only when its best physical area is clearly more likely.
        if second_score and best_score < second_score * 1.12:
            continue
        unambiguous.append((best_score, current_index, best_reference))

    # Prefer higher-inlier pairs while enforcing a one-to-one panorama
    # assignment. Multiple observations may legitimately occupy the same plan
    # cluster (for example, walking down and back through one corridor).
    selected = _select_unique_visual_matches(unambiguous)
    return sorted(selected, key=lambda item: item[1])


def _align_from_human_anchor_library(
    db: Session,
    *,
    capture: Capture,
    source: Path,
    relative_samples: list[SfMPathSample],
) -> PlanAlignment | None:
    """Use earlier DEVELOPMENT labels as reusable camera-to-plan landmarks."""
    previous_ids = list(
        db.scalars(
            select(Capture.id)
            .where(
                Capture.project_id == capture.project_id,
                Capture.start_floor_id == capture.start_floor_id,
                Capture.captured_at < capture.captured_at,
                Capture.dataset_split == "DEVELOPMENT",
                Capture.status.in_(["READY", "REVIEW_REQUIRED"]),
            )
            .order_by(Capture.captured_at.desc())
            # Select from the full project history first.  The actual labelled
            # assets are spatially deduplicated and capped below.  Limiting
            # captures here meant eight newer, unlabelled uploads could hide
            # every December/January Ground Truth observation.
            .limit(180)
        )
    )
    if not previous_ids:
        return None

    # PathControlPoint records are explicit calibration anchors. Development
    # evaluation points are also labels (holdout labels are excluded above).
    labelled: dict[uuid.UUID, tuple[str, float, float, datetime]] = {}
    evaluation_rows = db.execute(
        select(
            Keyframe.id,
            MediaFile.object_key,
            PathEvaluationPoint.target_x,
            PathEvaluationPoint.target_y,
            Capture.captured_at,
        )
        .select_from(Capture)
        .join(Keyframe, Keyframe.capture_id == Capture.id)
        .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
        .join(PathEvaluationPoint, PathEvaluationPoint.keyframe_id == Keyframe.id)
        .where(
            Capture.id.in_(previous_ids),
            Capture.dataset_split == "DEVELOPMENT",
            Keyframe.quality_status == "USABLE",
        )
    ).all()
    for keyframe_id, object_key, x, y, captured_at in evaluation_rows:
        labelled[keyframe_id] = (object_key, float(x), float(y), captured_at)
    control_rows = db.execute(
        select(
            Keyframe.id,
            MediaFile.object_key,
            PathControlPoint.x,
            PathControlPoint.y,
            Capture.captured_at,
        )
        .select_from(Capture)
        .join(Keyframe, Keyframe.capture_id == Capture.id)
        .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
        .join(PathControlPoint, PathControlPoint.keyframe_id == Keyframe.id)
        .where(
            Capture.id.in_(previous_ids),
            Capture.dataset_split == "DEVELOPMENT",
            Keyframe.quality_status == "USABLE",
        )
    ).all()
    for keyframe_id, object_key, x, y, captured_at in control_rows:
        labelled[keyframe_id] = (object_key, float(x), float(y), captured_at)
    if len(labelled) < PRIOR_MIN_ROUTE_MATCHES:
        return None

    assets = sorted(labelled.values(), key=lambda item: item[3], reverse=True)
    if len(assets) > ANCHOR_LIBRARY_LIMIT:
        # Retain spatial coverage rather than simply taking the newest cluster.
        grouped: dict[tuple[int, int], list[tuple[str, float, float, datetime]]] = {}
        for asset in assets:
            grouped.setdefault(_plan_cluster(asset[1], asset[2]), []).append(asset)
        assets = [values[0] for values in grouped.values()]
        if len(assets) > ANCHOR_LIBRARY_LIMIT:
            indices = np.linspace(0, len(assets) - 1, ANCHOR_LIBRARY_LIMIT, dtype=int)
            assets = [assets[int(index)] for index in indices]
    db.commit()

    with temporary_workspace(prefix="progress-anchor-align-") as temporary:
        workspace = Path(temporary)
        current_frames = _extract_prior_match_frames(source, workspace / "current")
        if len(current_frames) < 2:
            return None
        current_features = [_read_orb_features(path) for path in current_frames]
        reference_features: list[tuple[list[cv2.KeyPoint], np.ndarray | None]] = []
        reference_paths: list[Path] = []
        reference_positions: list[tuple[float, float]] = []
        for index, (object_key, x, y, _captured_at) in enumerate(assets):
            destination = workspace / f"anchor-{index:04d}.jpg"
            download_object(key=object_key, destination=str(destination))
            reference_paths.append(destination)
            reference_features.append(_read_orb_features(destination))
            reference_positions.append((x, y))
        alignment_source = "human-anchor-library-orb-v1"
        try:
            learned_scores = learned_panorama_matches(
                current_frames,
                reference_paths,
                workspace=workspace,
            )
            matches = _select_scored_labelled_anchor_matches(
                learned_scores,
                reference_positions,
            )
            alignment_source = "human-anchor-library-disk-lightglue-v1"
        except LearnedRelocalizationUnavailable:
            matches = _select_labelled_anchor_matches(
                current_features,
                reference_features,
                reference_positions,
            )
        except Exception:
            # The learned runtime is optional during staged deployment. Never
            # fail the whole capture; the conservative ORB gate can still try,
            # and a failed alignment remains REVIEW_REQUIRED rather than being
            # fabricated onto the plan.
            matches = _select_labelled_anchor_matches(
                current_features,
                reference_features,
                reference_positions,
            )

    minimum_index_span = max(2, round(len(current_frames) * 0.35))
    if (
        len(matches) < PRIOR_MIN_ROUTE_MATCHES
        or max((item[1] for item in matches), default=0)
        - min((item[1] for item in matches), default=0)
        < minimum_index_span
    ):
        return None
    correspondences: list[tuple[tuple[float, float], tuple[float, float]]] = []
    timestamps: list[int] = []
    for _score, current_index, reference_index in matches:
        timestamp_ms = current_index * PRIOR_MATCH_INTERVAL_SECONDS * 1000
        relative = _nearest_relative_point(relative_samples, timestamp_ms)
        correspondences.append(
            ((relative.x, relative.y), reference_positions[reference_index])
        )
        timestamps.append(timestamp_ms)
    return _anchor_constrained_alignment(
        relative_samples,
        correspondences,
        timestamps,
        start_x=float(capture.start_x),
        start_y=float(capture.start_y),
        source_label=alignment_source,
    )


def _align_from_previous_capture(
    db: Session,
    *,
    capture: Capture,
    source: Path,
    relative_samples: list[SfMPathSample],
) -> PlanAlignment | None:
    previous_candidates = list(
        db.scalars(
        select(Capture)
        .where(
            Capture.project_id == capture.project_id,
            Capture.start_floor_id == capture.start_floor_id,
            Capture.captured_at < capture.captured_at,
            Capture.dataset_split == "DEVELOPMENT",
            Capture.status.in_(["READY", "REVIEW_REQUIRED"]),
        )
        .order_by(Capture.captured_at.desc())
        # Automatic captures are deliberately not trusted as references. Look
        # farther back so the latest human-labelled capture is still available.
        .limit(180)
        )
    )
    if not previous_candidates:
        return None
    candidate_rows: list[
        tuple[Capture, list[tuple[Keyframe, MediaFile, CameraPose]]]
    ] = []
    for previous_capture in previous_candidates:
        verified_rows = list(
            db.execute(
                select(Keyframe, MediaFile, CameraPose)
                .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
                .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
                .where(
                    Keyframe.capture_id == previous_capture.id,
                    Keyframe.quality_status == "USABLE",
                    CameraPose.needs_review.is_(False),
                    # Never let an AI-only alignment become the reference for
                    # the next capture. A wrong automatic route would otherwise
                    # propagate through the project and still look VERIFIED.
                    or_(
                        CameraPose.reviewed_at.is_not(None),
                        CameraPose.algorithm.contains("dev-gt-piecewise-v1"),
                        # A Stella localization against a calibrated persistent
                        # map is already gated when it is written.  It must be
                        # eligible as the nearest chronological reference;
                        # otherwise the matcher skips a good previous day and
                        # jumps back to an older manually reviewed capture.
                        CameraPose.algorithm.contains("persistent-map-v1:"),
                        CameraPose.algorithm.contains("previous-hloc-sfm-v1:"),
                    ),
                )
                .order_by(Keyframe.timestamp_ms)
            ).all()
        )
        if len(verified_rows) >= 2:
            candidate_rows.append((previous_capture, verified_rows))
            if len(candidate_rows) >= 5:
                break
    if not candidate_rows:
        return None

    # Do not keep a SQLite read transaction open during frame extraction and
    # ORB matching (which can take several minutes for a long capture). A later
    # attempt to upgrade that transaction to a writer can otherwise race with
    # the viewer's status polling and fail with "database is locked".
    capture_start_x = float(capture.start_x)
    capture_start_y = float(capture.start_y)
    reference_assets: list[
        tuple[uuid.UUID, datetime, list[tuple[str, float, float]]]
    ] = []
    for previous, rows in candidate_rows:
        sparse_rows = [row for row in rows if row[0].is_warp_point]
        candidates = sparse_rows if len(sparse_rows) >= 2 else rows
        if len(candidates) > PRIOR_MATCH_LIMIT:
            indices = np.linspace(0, len(candidates) - 1, PRIOR_MATCH_LIMIT, dtype=int)
            candidates = [candidates[int(index)] for index in indices]
        reference_assets.append(
            (
                previous.id,
                previous.captured_at,
                [
                    (media.object_key, float(pose.x), float(pose.y))
                    for _keyframe, media, pose in candidates
                ],
            )
        )
    db.commit()

    with temporary_workspace(prefix="progress-prior-align-") as temporary:
        workspace = Path(temporary)
        current_frames = _extract_prior_match_frames(source, workspace / "current")
        if len(current_frames) < 2:
            return None
        for reference_index, (
            previous_id,
            _captured_at,
            candidate_assets,
        ) in enumerate(reference_assets):
            previous_paths: list[Path] = []
            for image_index, (object_key, _pose_x, _pose_y) in enumerate(
                candidate_assets
            ):
                destination = (
                    workspace / f"prior-{reference_index:02d}-{image_index:04d}.jpg"
                )
                download_object(key=object_key, destination=str(destination))
                previous_paths.append(destination)

            # Bind the current walk directly to a trusted multi-view 3-D map.
            # The retired ORB pair-ranking pass could not determine absolute
            # position and doubled processing time before HLoc.
            if reference_index < 3:
                try:
                    reference_positions = [
                        (pose_x, pose_y)
                        for _object_key, pose_x, pose_y in candidate_assets
                    ]
                    signature = hashlib.sha256(
                        repr(candidate_assets).encode("utf-8")
                    ).hexdigest()[:16]
                    plan_anchors = learned_3d_plan_anchors(
                        current_frames,
                        previous_paths,
                        reference_positions,
                        workspace=workspace / "nearest-3d",
                        cache_key=f"{previous_id.hex}-{signature}",
                    )
                    anchor_span = (
                        max(
                            (anchor.panorama_index for anchor in plan_anchors),
                            default=0,
                        )
                        - min(
                            (anchor.panorama_index for anchor in plan_anchors),
                            default=0,
                        )
                    )
                    logger.info(
                        "3-D previous-capture localization current=%s "
                        "reference=%s anchors=%d span=%d/%d faces=%d inliers=%d",
                        capture.id,
                        previous_id,
                        len(plan_anchors),
                        anchor_span,
                        len(current_frames),
                        sum(anchor.localized_faces for anchor in plan_anchors),
                        sum(anchor.inliers for anchor in plan_anchors),
                    )
                    if (
                        len(plan_anchors) >= max(8, PRIOR_MIN_ROUTE_MATCHES)
                        and anchor_span >= max(2, round(len(current_frames) * 0.80))
                    ):
                        correspondences = []
                        timestamps = []
                        for anchor in plan_anchors:
                            timestamp_ms = (
                                anchor.panorama_index
                                * PRIOR_MATCH_INTERVAL_SECONDS
                                * 1000
                            )
                            relative_point = _nearest_relative_point(
                                relative_samples, timestamp_ms
                            )
                            correspondences.append(
                                (
                                    (relative_point.x, relative_point.y),
                                    (anchor.plan_x, anchor.plan_y),
                                )
                            )
                            timestamps.append(timestamp_ms)
                        alignment = _anchor_constrained_alignment(
                            relative_samples,
                            correspondences,
                            timestamps,
                            start_x=capture_start_x,
                            start_y=capture_start_y,
                            source_label=f"previous-hloc-6dof-v2:{previous_id}",
                        )
                        # A validated 3-D localization result is stronger than
                        # the legacy pairwise 2-D matcher. Return it now so we
                        # neither spend another few minutes matching every
                        # panorama nor risk replacing it with an ambiguous fit.
                        if alignment is not None:
                            spatial_samples = [
                                SfMPathSample(
                                    timestamp_ms=(
                                        anchor.panorama_index
                                        * PRIOR_MATCH_INTERVAL_SECONDS
                                        * 1000
                                    ),
                                    x=anchor.visual_x,
                                    y=anchor.visual_y,
                                    heading_deg=0.0,
                                    confidence=min(1.0, anchor.inliers / 100.0),
                                    relative_z=anchor.visual_z,
                                    orientation_q=anchor.orientation_q,
                                )
                                for anchor in plan_anchors
                            ]
                            return replace(
                                alignment,
                                spatial_samples=spatial_samples,
                                spatial_camera_height=float(
                                    np.median(
                                        [
                                            anchor.visual_z
                                            - anchor.visual_ground_z
                                            for anchor in plan_anchors
                                        ]
                                    )
                                ),
                            )
                except LearnedRelocalizationUnavailable as exc:
                    logger.info(
                        "3-D learned relocalization unavailable for capture %s: %s",
                        capture.id,
                        exc,
                    )
                except Exception:
                    logger.exception(
                        "3-D previous-capture localization failed current=%s "
                        "reference=%s",
                        capture.id,
                        previous_id,
                    )
                # Pairwise 2-D image matches are useful diagnostics but are not
                # an absolute camera position.  They previously produced a
                # plausible-looking route and promoted it to READY even when
                # the plan placement was wrong.  Try another trusted 3-D map
                # instead; if none succeeds the capture remains for review.
                continue
            continue

        # No validated 3-D reference succeeded. Never turn pairwise 2-D image
        # similarity into an absolute plan route.
        return None

def estimate_capture_path(
    source: Path,
    *,
    start_x: float,
    start_y: float,
    end_timestamp_ms: int,
) -> list[EstimatedPathPoint]:
    sfm_samples = recover_visual_path(source, end_timestamp_ms=end_timestamp_ms)
    relative = [(sample.x, sample.y, sample.heading_deg) for sample in sfm_samples]
    fitted, _ = _fit_to_plan(
        relative,
        start_x,
        start_y,
        bounds=FLOOR_ONE_PLAN_BOUNDS,
    )
    return [
        EstimatedPathPoint(
            timestamp_ms=sample.timestamp_ms,
            pose=EstimatedPose(
                x=x,
                y=y,
                heading_deg=heading,
                confidence=sample.confidence,
                relative_z=sample.relative_z,
            ),
        )
        for sample, (x, y, heading) in zip(sfm_samples, fitted, strict=True)
    ]


def _poses_at_timestamps(
    path: list[EstimatedPathPoint], timestamps_ms: list[int]
) -> list[EstimatedPose]:
    if not path:
        raise LocalizationError("Localization did not produce a capture path")
    results: list[EstimatedPose] = []
    path_index = 0
    for timestamp_ms in timestamps_ms:
        while path_index + 1 < len(path) and path[path_index + 1].timestamp_ms <= timestamp_ms:
            path_index += 1
        current = path[path_index]
        if path_index + 1 >= len(path) or current.timestamp_ms == timestamp_ms:
            results.append(current.pose)
            continue
        following = path[path_index + 1]
        duration = following.timestamp_ms - current.timestamp_ms
        if duration <= 0:
            results.append(current.pose)
            continue
        ratio = min(1.0, max(0.0, (timestamp_ms - current.timestamp_ms) / duration))
        heading_delta = (
            following.pose.heading_deg - current.pose.heading_deg + 180
        ) % 360 - 180
        results.append(
            EstimatedPose(
                x=current.pose.x + (following.pose.x - current.pose.x) * ratio,
                y=current.pose.y + (following.pose.y - current.pose.y) * ratio,
                heading_deg=(current.pose.heading_deg + heading_delta * ratio) % 360,
                confidence=current.pose.confidence
                + (following.pose.confidence - current.pose.confidence) * ratio,
                relative_z=current.pose.relative_z
                + (following.pose.relative_z - current.pose.relative_z) * ratio,
            )
        )
    return results


def _spatial_samples_at_timestamps(
    samples: list[SfMPathSample], timestamps_ms: list[int]
) -> list[SfMPathSample]:
    """Interpolate one rigid 6-DoF reconstruction without mixing SLAM frames."""
    if len(samples) < 2 or any(sample.orientation_q is None for sample in samples):
        raise LocalizationError("6-DoF localization did not cover enough panoramas")
    ordered = sorted(samples, key=lambda sample: sample.timestamp_ms)
    source_times = np.asarray([sample.timestamp_ms for sample in ordered], dtype=float)
    target_times = np.asarray(timestamps_ms, dtype=float)
    quaternions = np.asarray([sample.orientation_q for sample in ordered], dtype=float)
    for index in range(1, len(quaternions)):
        if float(np.dot(quaternions[index - 1], quaternions[index])) < 0:
            quaternions[index] *= -1
    components = np.column_stack(
        [
            np.interp(target_times, source_times, quaternions[:, axis])
            for axis in range(4)
        ]
    )
    components /= np.maximum(np.linalg.norm(components, axis=1, keepdims=True), 1e-9)
    xs = np.interp(target_times, source_times, [sample.x for sample in ordered])
    ys = np.interp(target_times, source_times, [sample.y for sample in ordered])
    zs = np.interp(
        target_times, source_times, [sample.relative_z for sample in ordered]
    )
    confidences = np.interp(
        target_times, source_times, [sample.confidence for sample in ordered]
    )
    return [
        SfMPathSample(
            timestamp_ms=timestamp_ms,
            x=float(x),
            y=float(y),
            heading_deg=0.0,
            confidence=float(confidence),
            relative_z=float(z),
            orientation_q=tuple(float(value) for value in quaternion),
        )
        for timestamp_ms, x, y, z, confidence, quaternion in zip(
            timestamps_ms, xs, ys, zs, confidences, components, strict=True
        )
    ]


def estimate_keyframe_poses(
    source: Path,
    *,
    keyframe_timestamps_ms: list[int],
    start_x: float,
    start_y: float,
) -> list[EstimatedPose]:
    end_timestamp_ms = max(keyframe_timestamps_ms, default=0)
    path = estimate_capture_path(
        source,
        start_x=start_x,
        start_y=start_y,
        end_timestamp_ms=end_timestamp_ms,
    )
    return _poses_at_timestamps(path, keyframe_timestamps_ms)


def _stella_map_object_key(capture: Capture) -> str:
    return (
        f"projects/{capture.project_id}/captures/{capture.id}/"
        "localization/stella-map.msg"
    )


def _spatial_model_object_key(capture: Capture) -> str:
    return (
        f"projects/{capture.project_id}/captures/{capture.id}/"
        "localization/spatial-model.json"
    )


def _select_persistent_map_reference(
    db: Session, *, capture: Capture
) -> PersistentMapReference | None:
    """Choose the newest trusted map while retaining a human calibration root."""
    # Calibration captures are permanent project assets.  Do not derive this
    # set from the recent-capture window below: after enough uploads the human
    # calibrated root would fall out of that window and every later capture
    # would silently lose its absolute plan coordinate system.
    calibration_rows = db.execute(
        select(Capture, func.count(PathControlPoint.id))
        .join(PathControlPoint, PathControlPoint.capture_id == Capture.id)
        .where(
            Capture.project_id == capture.project_id,
            Capture.start_floor_id == capture.start_floor_id,
            Capture.id != capture.id,
            Capture.captured_at < capture.captured_at,
            Capture.dataset_split == "DEVELOPMENT",
            Capture.status.in_(["READY", "REVIEW_REQUIRED"]),
        )
        .group_by(Capture.id)
        .having(func.count(PathControlPoint.id) >= PERSISTENT_MAP_MIN_CONTROL_POINTS)
        .order_by(Capture.captured_at.desc())
    ).all()
    calibrated_by_prefix = {
        str(calibration.id)[:8]: calibration
        for calibration, _control_count in calibration_rows
    }
    if not calibrated_by_prefix:
        return None

    candidates = list(
        db.scalars(
            select(Capture)
            .where(
                Capture.project_id == capture.project_id,
                Capture.start_floor_id == capture.start_floor_id,
                Capture.id != capture.id,
                Capture.captured_at < capture.captured_at,
                Capture.dataset_split == "DEVELOPMENT",
                Capture.status.in_(["READY", "REVIEW_REQUIRED"]),
            )
            .order_by(Capture.captured_at.desc())
            # Maps are small and this query runs once per capture.  Looking
            # farther back is preferable to discarding the last trusted map on
            # projects with frequent daily captures.
            .limit(180)
        )
    )
    map_media: dict[uuid.UUID, MediaFile] = {}
    for candidate in candidates:
        key = _stella_map_object_key(candidate)
        media = db.scalar(
            select(MediaFile).where(
                MediaFile.project_id == capture.project_id,
                MediaFile.object_key == key,
                MediaFile.upload_status == "READY",
            )
        )
        if media is None:
            continue
        map_media[candidate.id] = media
    for candidate in candidates:
        media = map_media.get(candidate.id)
        if media is None:
            continue
        calibration = calibrated_by_prefix.get(str(candidate.id)[:8])
        if calibration is None and candidate.status == "READY":
            algorithm = db.scalar(
                select(CameraPose.algorithm)
                .join(Keyframe, Keyframe.id == CameraPose.keyframe_id)
                .where(
                    Keyframe.capture_id == candidate.id,
                    CameraPose.needs_review.is_(False),
                    CameraPose.algorithm.contains("persistent-map-v1:"),
                )
                .limit(1)
            )
            if algorithm:
                parts = algorithm.split("persistent-map-v1:", 1)[1].split(":", 1)
                calibration = calibrated_by_prefix.get(parts[0])
        if calibration is not None:
            return PersistentMapReference(
                map_capture_id=candidate.id,
                calibration_capture_id=calibration.id,
                object_key=media.object_key,
                start_x=float(calibration.start_x),
                start_y=float(calibration.start_y),
            )
    return None


def _align_from_existing_reviewed_prefix(
    db: Session,
    *,
    capture: Capture,
    relative_samples: list[SfMPathSample],
) -> PlanAlignment | None:
    """Extend a recovered track using the capture's reviewed, moving prefix.

    A long capture may already have a human-confirmed plan transform even when
    its original visual trajectory froze after tracking loss.  Reusing the
    valid prefix keeps that transform and avoids an unnecessary cross-capture
    image search after segmented Stella recovery fills in the missing tail.
    """
    rows = list(
        db.execute(
            select(Keyframe, CameraPose)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .where(
                Keyframe.capture_id == capture.id,
                CameraPose.visual_x.is_not(None),
                CameraPose.visual_y.is_not(None),
                CameraPose.needs_review.is_(False),
                CameraPose.reviewed_at.is_not(None),
            )
            .order_by(Keyframe.timestamp_ms)
        ).all()
    )
    if len(rows) < 3:
        return None

    moving_rows: list[tuple[Keyframe, CameraPose]] = [rows[0]]
    previous_visual = (float(rows[0][1].visual_x), float(rows[0][1].visual_y))
    for row in rows[1:]:
        visual = (float(row[1].visual_x), float(row[1].visual_y))
        if math.hypot(visual[0] - previous_visual[0], visual[1] - previous_visual[1]) > 1e-5:
            moving_rows.append(row)
            previous_visual = visual
    if len(moving_rows) < 3:
        return None

    # Use a compact, evenly distributed set so repeated high-frequency poses
    # cannot outweigh the manually confirmed route shape.
    if len(moving_rows) > 24:
        indices = np.linspace(0, len(moving_rows) - 1, 24, dtype=int)
        moving_rows = [moving_rows[int(index)] for index in indices]
    correspondences: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for keyframe, pose in moving_rows:
        recovered = _nearest_relative_point(relative_samples, keyframe.timestamp_ms)
        correspondences.append(
            (
                (recovered.x, recovered.y),
                (float(pose.x), float(pose.y)),
            )
        )
    similarity = _estimate_prior_similarity(
        correspondences,
        start_x=float(capture.start_x),
        start_y=float(capture.start_y),
    )
    if similarity is None:
        return None
    scale, rotation_deg, mirror, confidence, inlier_count = similarity
    relative = [(sample.x, sample.y, sample.heading_deg) for sample in relative_samples]
    return PlanAlignment(
        points=_transform_with_fixed_start(
            relative,
            start_x=float(capture.start_x),
            start_y=float(capture.start_y),
            scale=scale,
            rotation_deg=rotation_deg,
            mirror=mirror,
        ),
        scale=scale,
        rotation_deg=rotation_deg,
        mirror=mirror,
        confidence=confidence,
        source=(
            f"existing-reviewed-prefix-v1:{inlier_count}-anchors"
            f"{'-mirror' if mirror else ''}"
        ),
    )


def _save_persistent_map(
    db: Session, *, capture: Capture, map_path: Path
) -> None:
    """Persist Stella's map so later captures can relocalize in one coordinate frame."""
    if not map_path.is_file() or map_path.stat().st_size <= 0:
        return
    key = _stella_map_object_key(capture)
    upload_file(
        key=key,
        source=str(map_path),
        content_type="application/octet-stream",
    )
    media = db.scalar(select(MediaFile).where(MediaFile.object_key == key))
    if media is None:
        media = MediaFile(
            project_id=capture.project_id,
            media_kind="SLAM_MAP",
            bucket=get_settings().s3_bucket,
            object_key=key,
            original_filename="stella-map.msg",
            content_type="application/octet-stream",
            size_bytes=map_path.stat().st_size,
            upload_status="READY",
        )
        db.add(media)
    else:
        media.size_bytes = map_path.stat().st_size
        media.upload_status = "READY"
    db.commit()


def _save_spatial_model(
    db: Session, *, capture: Capture, model_path: Path
) -> None:
    """Persist the SfM point cloud used by the 3-D/2-D station inspector."""
    if not model_path.is_file() or model_path.stat().st_size <= 0:
        return
    key = _spatial_model_object_key(capture)
    upload_file(key=key, source=str(model_path), content_type="application/json")
    media = db.scalar(select(MediaFile).where(MediaFile.object_key == key))
    if media is None:
        media = MediaFile(
            project_id=capture.project_id,
            media_kind="SFM_SPATIAL_MODEL",
            bucket=get_settings().s3_bucket,
            object_key=key,
            original_filename="spatial-model.json",
            content_type="application/json",
            size_bytes=model_path.stat().st_size,
            upload_status="READY",
        )
        db.add(media)
    else:
        media.size_bytes = model_path.stat().st_size
        media.upload_status = "READY"
    db.commit()


def _align_from_persistent_map(
    db: Session,
    *,
    capture: Capture,
    reference: PersistentMapReference,
    map_samples: list[SfMPathSample],
) -> PlanAlignment | None:
    """Transform a relocalized Stella route using the reference's human anchors."""
    rows = list(
        db.execute(
            select(PathControlPoint, CameraPose)
            .join(Keyframe, Keyframe.id == PathControlPoint.keyframe_id)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .where(
                PathControlPoint.capture_id == reference.calibration_capture_id,
                CameraPose.visual_x.is_not(None),
                CameraPose.visual_y.is_not(None),
            )
        ).all()
    )
    if len(rows) < PERSISTENT_MAP_MIN_CONTROL_POINTS:
        return None
    source = np.float32(
        [[float(pose.visual_x), float(pose.visual_y)] for _control, pose in rows]
    )
    target = np.float32(
        [[float(control.x), float(control.y)] for control, _pose in rows]
    )
    if np.ptp(source[:, 0]) < 1e-4 or np.ptp(source[:, 1]) < 1e-4:
        return None
    matrix, mask = cv2.estimateAffine2D(
        source,
        target,
        method=cv2.RANSAC,
        ransacReprojThreshold=PRIOR_MAX_PLAN_RESIDUAL,
        maxIters=5000,
        confidence=0.995,
        refineIters=20,
    )
    if matrix is None or mask is None:
        return None
    inliers = mask.reshape(-1).astype(bool)
    inlier_count = int(inliers.sum())
    if inlier_count < PERSISTENT_MAP_MIN_CONTROL_POINTS:
        return None
    predicted_anchors = cv2.transform(source.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    residual = float(
        np.mean(np.linalg.norm(predicted_anchors[inliers] - target[inliers], axis=1))
    )
    linear = matrix[:, :2]
    singular_values = np.linalg.svd(linear, compute_uv=False)
    if singular_values.min() <= 1e-8:
        return None
    anisotropy = float(singular_values.max() / singular_values.min())
    if anisotropy > PRIOR_MAX_AFFINE_ANISOTROPY:
        return None

    transformed: list[tuple[float, float, float]] = []
    for sample in map_samples:
        plan = linear @ np.asarray([sample.x, sample.y]) + matrix[:, 2]
        direction = linear @ np.asarray(
            [
                math.cos(math.radians(sample.heading_deg)),
                math.sin(math.radians(sample.heading_deg)),
            ]
        )
        transformed.append(
            (
                float(plan[0]),
                float(plan[1]),
                math.degrees(math.atan2(direction[1], direction[0])) % 360.0,
            )
        )
    if not transformed:
        return None
    start_error = math.hypot(
        transformed[0][0] - float(capture.start_x),
        transformed[0][1] - float(capture.start_y),
    )
    if start_error > PERSISTENT_MAP_MAX_START_ERROR:
        return None
    # The selected start remains a hard observation. Apply only a small global
    # translation; route shape, scale and rotation stay in the shared map frame.
    offset_x = float(capture.start_x) - transformed[0][0]
    offset_y = float(capture.start_y) - transformed[0][1]
    points = [
        (
            min(1.0, max(0.0, x + offset_x)),
            min(1.0, max(0.0, y + offset_y)),
            heading,
        )
        for x, y, heading in transformed
    ]
    inlier_ratio = inlier_count / len(rows)
    residual_score = max(0.0, 1.0 - residual / PRIOR_MAX_PLAN_RESIDUAL)
    confidence = min(0.99, 0.55 + 0.30 * inlier_ratio + 0.15 * residual_score)
    return PlanAlignment(
        points=points,
        scale=float(np.mean(singular_values)),
        rotation_deg=math.degrees(math.atan2(linear[1, 0], linear[0, 0])),
        mirror=float(np.linalg.det(linear)) < 0,
        confidence=confidence,
        source=(
            f"persistent-map-v1:{str(reference.calibration_capture_id)[:8]}:"
            f"{inlier_count}-anchors"
        ),
    )


def save_camera_poses(
    db: Session,
    *,
    capture: Capture,
    job: ProcessingJob,
    source: Path,
) -> list[CameraPose]:
    algorithm_version = _visual_algorithm_version()
    keyframes = list(
        db.scalars(
            select(Keyframe)
            .where(Keyframe.capture_id == capture.id)
            .order_by(Keyframe.timestamp_ms)
        )
    )
    if not keyframes:
        raise LocalizationError("ยังไม่มี Keyframe สำหรับ Localization")
    end_timestamp_ms = max(item.timestamp_ms for item in keyframes)
    reviewed_existing_count = int(
        db.scalar(
            select(func.count(CameraPose.id))
            .join(Keyframe, CameraPose.keyframe_id == Keyframe.id)
            .where(
                Keyframe.capture_id == capture.id,
                CameraPose.visual_x.is_not(None),
                CameraPose.visual_y.is_not(None),
                CameraPose.needs_review.is_(False),
                CameraPose.reviewed_at.is_not(None),
            )
        )
        or 0
    )
    # A reviewed transform on this capture is stronger than a historical map.
    # Recover a fresh relative track so its valid prefix can extend the same
    # human-confirmed placement after a prior tracking loss.
    persistent_reference = (
        None
        if reviewed_existing_count >= 3
        else _select_persistent_map_reference(db, capture=capture)
    )
    map_input: Path | None = None
    map_output = source.parent / f"stella-map-{capture.id}.msg"
    spatial_model_output = source.parent / f"spatial-model-{capture.id}.json"
    if persistent_reference is not None:
        map_input = source.parent / (
            f"reference-map-{persistent_reference.map_capture_id}.msg"
        )
        db.commit()
        download_object(key=persistent_reference.object_key, destination=str(map_input))
    try:
        relative_samples = recover_visual_path(
            source,
            end_timestamp_ms=end_timestamp_ms,
            map_db_input=map_input,
            map_db_output=map_output,
            spatial_model_output=spatial_model_output,
        )
    except StellaLocalizationError:
        if map_input is None:
            raise
        # Construction appearance can change enough that an old map cannot be
        # relocalized. Build a fresh map and keep it behind the review gate.
        persistent_reference = None
        relative_samples = recover_visual_path(
            source,
            end_timestamp_ms=end_timestamp_ms,
            map_db_output=map_output,
            spatial_model_output=spatial_model_output,
        )
    _save_persistent_map(db, capture=capture, map_path=map_output)
    _save_spatial_model(db, capture=capture, model_path=spatial_model_output)
    # This helper is also called by the video pipeline after keyframe extraction
    # has already advanced the job to 75%. Never make a running job appear to
    # move backwards while the (potentially slow) cross-capture alignment runs.
    job.progress_percent = max(job.progress_percent, 65)
    db.commit()
    # Prefer reusable, explicitly labelled camera positions.  They are the
    # project equivalent of fixed grid/column landmarks and are substantially
    # safer than inheriting an entire previous route.  The older whole-capture
    # matcher remains a fallback for projects that do not have enough labels.
    alignment = _align_from_existing_reviewed_prefix(
        db,
        capture=capture,
        relative_samples=relative_samples,
    )
    if persistent_reference is not None:
        if alignment is None:
            alignment = _align_from_persistent_map(
                db,
                capture=capture,
                reference=persistent_reference,
                map_samples=relative_samples,
            )
    if alignment is None:
        alignment = _align_from_human_anchor_library(
            db,
            capture=capture,
            source=source,
            relative_samples=relative_samples,
        )
    if alignment is None:
        alignment = _align_from_previous_capture(
            db,
            capture=capture,
            source=source,
            relative_samples=relative_samples,
        )
    if alignment is None:
        # Stella has recovered a connected *relative* camera trajectory, but
        # no evidence was strong enough to bind it to absolute plan
        # coordinates.  Do not fabricate a plausible-looking route by fitting
        # the unknown trajectory into the building footprint.  Keep the visual
        # trajectory in visual_x/visual_y for the calibration tools and publish
        # only the user-supplied t=0 anchor until relocalization or a human
        # transform supplies the missing plan transform.
        start_x = float(capture.start_x)
        start_y = float(capture.start_y)
        anchored = [(start_x, start_y, sample.heading_deg) for sample in relative_samples]
        alignment = PlanAlignment(
            points=anchored,
            scale=1.0,
            rotation_deg=0.0,
            mirror=False,
            confidence=0.0,
            source="unaligned-start-anchor-v1",
        )
    job.progress_percent = max(job.progress_percent, 85)
    db.commit()
    path_estimates = [
        EstimatedPathPoint(
            timestamp_ms=sample.timestamp_ms,
            pose=EstimatedPose(
                x=x,
                y=y,
                heading_deg=heading,
                confidence=min(sample.confidence, alignment.confidence),
                relative_z=sample.relative_z,
            ),
        )
        for sample, (x, y, heading) in zip(
            relative_samples, alignment.points, strict=True
        )
    ]
    estimates = _poses_at_timestamps(
        path_estimates,
        [item.timestamp_ms for item in keyframes],
    )
    visual_path = [
        EstimatedPathPoint(
            timestamp_ms=sample.timestamp_ms,
            pose=EstimatedPose(
                x=sample.x,
                y=sample.y,
                heading_deg=sample.heading_deg,
                confidence=sample.confidence,
                relative_z=sample.relative_z,
            ),
        )
        for sample in relative_samples
    ]
    visual_estimates = _poses_at_timestamps(
        visual_path,
        [item.timestamp_ms for item in keyframes],
    )
    db.execute(delete(CapturePathPoint).where(CapturePathPoint.capture_id == capture.id))
    for path_estimate in path_estimates:
        path_pose = path_estimate.pose
        db.add(
            CapturePathPoint(
                capture_id=capture.id,
                floor_id=capture.start_floor_id,
                timestamp_ms=path_estimate.timestamp_ms,
                x=Decimal(str(round(path_pose.x, 6))),
                y=Decimal(str(round(path_pose.y, 6))),
                heading_deg=Decimal(str(round(path_pose.heading_deg % 360.0, 3) % 360.0)),
                confidence=Decimal(str(round(path_pose.confidence, 5))),
                localization_run_id=job.id,
                algorithm=f"{algorithm_version}:{alignment.source}"[:80],
            )
        )
    keyframe_ids = [item.id for item in keyframes]
    db.execute(delete(CameraPose).where(CameraPose.keyframe_id.in_(keyframe_ids)))
    poses: list[CameraPose] = []
    for keyframe, estimate, visual in zip(
        keyframes, estimates, visual_estimates, strict=True
    ):
        pose = CameraPose(
            keyframe_id=keyframe.id,
            floor_id=capture.start_floor_id,
            x=Decimal(str(round(estimate.x, 6))),
            y=Decimal(str(round(estimate.y, 6))),
            heading_deg=Decimal(str(round(estimate.heading_deg % 360.0, 3) % 360.0)),
            visual_x=Decimal(str(round(visual.x, 6))),
            visual_y=Decimal(str(round(visual.y, 6))),
            visual_heading_deg=Decimal(
                str(round(visual.heading_deg % 360.0, 3) % 360.0)
            ),
            relative_z_m=Decimal(str(round(visual.relative_z, 6))),
            # This score describes the visual reconstruction only. Absolute
            # floor-plan certainty is represented separately by ``needs_review``.
            confidence=Decimal(str(round(visual.confidence, 5))),
            localization_run_id=job.id,
            algorithm=f"{algorithm_version}:{alignment.source}"[:80],
            # Visual matching can propose a useful draft but cannot certify an
            # absolute floor-plan position. Only a later human transform or
            # labelled development correction may clear this flag.
            needs_review=not _alignment_is_auto_accepted(alignment),
        )
        db.add(pose)
        poses.append(pose)
    pose_by_keyframe = {pose.keyframe_id: pose for pose in poses}
    evaluation_points = list(
        db.scalars(
            select(PathEvaluationPoint).where(
                PathEvaluationPoint.capture_id == capture.id
            )
        )
    )
    for evaluation in evaluation_points:
        pose = pose_by_keyframe.get(evaluation.keyframe_id)
        if pose is None:
            continue
        predicted_x = float(pose.x)
        predicted_y = float(pose.y)
        error = math.hypot(
            predicted_x - float(evaluation.target_x),
            predicted_y - float(evaluation.target_y),
        )
        evaluation.localization_run_id = job.id
        evaluation.predicted_x = Decimal(str(round(predicted_x, 6)))
        evaluation.predicted_y = Decimal(str(round(predicted_y, 6)))
        evaluation.error_normalized = Decimal(str(round(error, 8)))
        evaluation.is_within_tolerance = error <= float(
            evaluation.tolerance_normalized
        )
    db.commit()
    return poses


def realign_existing_camera_poses(
    db: Session,
    *,
    capture: Capture,
    job: ProcessingJob,
    source: Path,
) -> list[CameraPose] | None:
    """Relocalize an existing visual trajectory without running SLAM again.

    Retrying localization used to replay the complete 8K walk through Stella
    even when every keyframe already had immutable visual coordinates.  That is
    both slow and unnecessary: HLoc only needs the source panoramas plus those
    relative coordinates to bind the walk to a trusted previous 3-D map.

    ``None`` means that the capture does not have a sufficiently complete
    visual trajectory, or that no absolute plan alignment passed validation;
    callers may then run the full SLAM pipeline.  A failed match never mutates
    the existing route.
    """
    rows = list(
        db.execute(
            select(Keyframe, CameraPose)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .where(
                Keyframe.capture_id == capture.id,
                CameraPose.visual_x.is_not(None),
                CameraPose.visual_y.is_not(None),
                CameraPose.visual_heading_deg.is_not(None),
            )
            .order_by(Keyframe.timestamp_ms)
        ).all()
    )
    keyframe_count = int(
        db.scalar(
            select(func.count(Keyframe.id)).where(Keyframe.capture_id == capture.id)
        )
        or 0
    )
    if len(rows) < 2 or len(rows) < max(2, math.ceil(keyframe_count * 0.9)):
        return None

    # A previous Stella run can contain a pose row for every keyframe even
    # though tracking stopped early; interpolation then repeats the last pose
    # for the remainder of the video. Do not reuse that frozen trajectory for
    # relocalization. Force a fresh run, whose Stella adapter can recover it in
    # overlapping segments.
    first_motion_timestamp: int | None = None
    last_motion_timestamp = rows[0][0].timestamp_ms
    previous_x = float(rows[0][1].visual_x)
    previous_y = float(rows[0][1].visual_y)
    for keyframe, pose in rows[1:]:
        x = float(pose.visual_x)
        y = float(pose.visual_y)
        if math.hypot(x - previous_x, y - previous_y) > 1e-5:
            if first_motion_timestamp is None:
                first_motion_timestamp = keyframe.timestamp_ms
            last_motion_timestamp = keyframe.timestamp_ms
        previous_x, previous_y = x, y
    final_timestamp = rows[-1][0].timestamp_ms
    frozen_prefix_ms = first_motion_timestamp or final_timestamp
    frozen_tail_ms = final_timestamp - last_motion_timestamp
    frozen_limit_ms = max(10_000, int(final_timestamp * 0.25))
    if frozen_prefix_ms > frozen_limit_ms or frozen_tail_ms > frozen_limit_ms:
        return None

    relative_samples = [
        SfMPathSample(
            timestamp_ms=keyframe.timestamp_ms,
            x=float(pose.visual_x),
            y=float(pose.visual_y),
            heading_deg=float(pose.visual_heading_deg),
            confidence=float(pose.confidence),
            relative_z=float(pose.relative_z_m or 0),
        )
        for keyframe, pose in rows
    ]
    alignment = _align_from_previous_capture(
        db,
        capture=capture,
        source=source,
        relative_samples=relative_samples,
    )
    if alignment is None:
        return None

    accepted = _alignment_is_auto_accepted(alignment)
    spatial_estimates = (
        _spatial_samples_at_timestamps(
            alignment.spatial_samples,
            [keyframe.timestamp_ms for keyframe, _pose in rows],
        )
        if alignment.spatial_samples is not None
        and alignment.spatial_camera_height is not None
        else None
    )
    algorithm = f"{STELLA_ALGORITHM_VERSION}:{alignment.source}"[:80]
    db.execute(delete(CapturePathPoint).where(CapturePathPoint.capture_id == capture.id))
    pose_by_keyframe: dict[uuid.UUID, CameraPose] = {}
    for row_index, ((keyframe, pose), (x, y, heading)) in enumerate(zip(
        rows, alignment.points, strict=True
    )
    ):
        bounded_x = min(1.0, max(0.0, x))
        bounded_y = min(1.0, max(0.0, y))
        bounded_heading = heading % 360.0
        pose.floor_id = capture.start_floor_id
        pose.x = Decimal(str(round(bounded_x, 6)))
        pose.y = Decimal(str(round(bounded_y, 6)))
        pose.heading_deg = Decimal(str(round(bounded_heading, 3) % 360.0))
        pose.localization_run_id = job.id
        pose.algorithm = algorithm
        pose.needs_review = not accepted
        spatial = spatial_estimates[row_index] if spatial_estimates is not None else None
        pose.visual_x = (
            Decimal(str(round(spatial.x, 6))) if spatial is not None else pose.visual_x
        )
        pose.visual_y = (
            Decimal(str(round(spatial.y, 6))) if spatial is not None else pose.visual_y
        )
        pose.visual_z = (
            Decimal(str(round(spatial.relative_z, 6))) if spatial is not None else None
        )
        pose.visual_ground_z = (
            Decimal(
                str(
                    round(
                        spatial.relative_z - float(alignment.spatial_camera_height),
                        6,
                    )
                )
            )
            if spatial is not None
            else None
        )
        quaternion = spatial.orientation_q if spatial is not None else None
        pose.orientation_qx = Decimal(str(round(quaternion[0], 8))) if quaternion else None
        pose.orientation_qy = Decimal(str(round(quaternion[1], 8))) if quaternion else None
        pose.orientation_qz = Decimal(str(round(quaternion[2], 8))) if quaternion else None
        pose.orientation_qw = Decimal(str(round(quaternion[3], 8))) if quaternion else None
        pose.visibility_target_ids = None
        if accepted:
            # This is a new automatic run, not a human verification event.
            pose.reviewed_by_id = None
            pose.reviewed_at = None
        pose_by_keyframe[keyframe.id] = pose
        db.add(
            CapturePathPoint(
                capture_id=capture.id,
                floor_id=capture.start_floor_id,
                timestamp_ms=keyframe.timestamp_ms,
                x=pose.x,
                y=pose.y,
                heading_deg=pose.heading_deg,
                confidence=Decimal(
                    str(round(min(float(pose.confidence), alignment.confidence), 5))
                ),
                localization_run_id=job.id,
                algorithm=algorithm,
            )
        )

    for evaluation in db.scalars(
        select(PathEvaluationPoint).where(PathEvaluationPoint.capture_id == capture.id)
    ):
        pose = pose_by_keyframe.get(evaluation.keyframe_id)
        if pose is None:
            continue
        predicted_x = float(pose.x)
        predicted_y = float(pose.y)
        error = math.hypot(
            predicted_x - float(evaluation.target_x),
            predicted_y - float(evaluation.target_y),
        )
        evaluation.localization_run_id = job.id
        evaluation.predicted_x = Decimal(str(round(predicted_x, 6)))
        evaluation.predicted_y = Decimal(str(round(predicted_y, 6)))
        evaluation.error_normalized = Decimal(str(round(error, 8)))
        evaluation.is_within_tolerance = error <= float(
            evaluation.tolerance_normalized
        )

    evaluation_points = list(
        db.scalars(
            select(PathEvaluationPoint).where(
                PathEvaluationPoint.capture_id == capture.id
            )
        )
    )
    if evaluation_points:
        within_count = sum(point.is_within_tolerance for point in evaluation_points)
        accepted = (
            accepted
            and len(evaluation_points) >= 20
            and within_count / len(evaluation_points) >= 0.90
        )
    if spatial_estimates is None:
        accepted = False
    for _keyframe, pose in rows:
        pose.needs_review = not accepted

    job.progress_percent = max(job.progress_percent, 85)
    db.commit()
    logger.info(
        "Reused existing visual trajectory capture=%s poses=%d source=%s "
        "confidence=%.3f accepted=%s",
        capture.id,
        len(rows),
        alignment.source,
        alignment.confidence,
        accepted,
    )
    return [pose for _keyframe, pose in rows]


def localize_capture_job(db: Session, job_id: uuid.UUID) -> dict[str, object]:
    job = db.get(ProcessingJob, job_id)
    # Celery messages can outlive a user cancellation.  Treat terminal jobs as
    # idempotent so a stale queue message cannot revive the job and overwrite
    # the capture's existing route.
    if job is not None and job.status in {"SUCCEEDED", "CANCELLED"}:
        pose_count = db.scalar(
            select(func.count(CameraPose.id))
            .join(Keyframe, CameraPose.keyframe_id == Keyframe.id)
            .where(Keyframe.capture_id == job.capture_id)
        )
        return {
            "job_id": str(job.id),
            "status": job.status,
            "pose_count": int(pose_count or 0),
        }
    capture = db.get(Capture, job.capture_id) if job else None
    media = db.get(MediaFile, capture.source_video_id) if capture else None
    if job is None or capture is None or media is None or media.upload_status != "READY":
        raise LocalizationError("Capture หรือวิดีโอต้นทางยังไม่พร้อม")
    try:
        job.status = "RUNNING"
        job.progress_percent = 10
        job.started_at = job.started_at or utc_now()
        job.finished_at = None
        job.error_code = None
        job.error_message = None
        capture.status = "LOCALIZING"
        db.commit()
        with temporary_workspace(prefix="progress-localize-job-") as temporary:
            source = Path(temporary) / "source.mp4"
            download_media_file(
                bucket=media.bucket,
                key=media.object_key,
                destination=str(source),
            )
            job.progress_percent = 35
            db.commit()
            poses = realign_existing_camera_poses(
                db,
                capture=capture,
                job=job,
                source=source,
            )
            if poses is None:
                poses = save_camera_poses(db, capture=capture, job=job, source=source)
        job.status = "SUCCEEDED"
        job.progress_percent = 100
        job.finished_at = utc_now()
        capture.status = "REVIEW_REQUIRED" if any(p.needs_review for p in poses) else "READY"
        db.commit()
        return {"job_id": str(job.id), "status": job.status, "pose_count": len(poses)}
    except Exception as exc:
        db.rollback()
        job = db.get(ProcessingJob, job_id)
        capture = db.get(Capture, job.capture_id) if job else None
        if job:
            job.status = "FAILED"
            job.error_code = type(exc).__name__
            job.error_message = str(exc)[:3000]
            job.finished_at = utc_now()
        if capture:
            capture.status = "LOCALIZATION_FAILED"
        db.commit()
        raise
