from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from progress_api.config import get_settings
from progress_api.services.sfm_localization import SfMPathSample
from progress_api.services.temporary_workspace import temporary_workspace

VIO_ALGORITHM_VERSION = "metric-visual-inertial-v1"
MINIMUM_COVERAGE_RATIO = 0.90
MAXIMUM_SAMPLE_GAP_MS = 1_500
MAXIMUM_WALKING_SPEED_M_S = 4.0
MINIMUM_PATH_LENGTH_M = 0.50


class VisualInertialLocalizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class VisualInertialQuality:
    coverage_ratio: float
    path_length_m: float
    maximum_speed_m_s: float
    maximum_gap_ms: int


def _heading_from_quaternion(quaternion: tuple[float, float, float, float]) -> float:
    """Return heading of the panorama's centre ray in the canonical world."""
    x, y, z, w = quaternion
    # The panorama camera frame is X-right, Y-down, Z-forward. The third
    # rotation-matrix column is therefore the centre ray in world coordinates.
    forward_world_x = 2.0 * (x * z + y * w)
    forward_world_y = 2.0 * (y * z - x * w)
    horizontal_norm = math.hypot(forward_world_x, forward_world_y)
    if horizontal_norm < 1e-6:
        raise VisualInertialLocalizationError("VIO camera forward ray is vertical")
    return math.degrees(math.atan2(forward_world_y, forward_world_x)) % 360.0


def _parse_trajectory(path: Path) -> list[SfMPathSample]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualInertialLocalizationError("VIO runner did not write valid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
        raise VisualInertialLocalizationError("VIO output must contain a samples array")
    if payload.get("coordinate_frame") != "x-forward_y-left_z-up":
        raise VisualInertialLocalizationError("VIO output uses an unsupported coordinate frame")
    if payload.get("position_unit") != "metre":
        raise VisualInertialLocalizationError("VIO output positions must be metric")

    samples: list[SfMPathSample] = []
    for row in payload["samples"]:
        if not isinstance(row, dict):
            raise VisualInertialLocalizationError("VIO sample must be an object")
        position = row.get("position_m")
        quaternion = row.get("camera_to_world_xyzw")
        if not (
            isinstance(position, list)
            and len(position) == 3
            and isinstance(quaternion, list)
            and len(quaternion) == 4
        ):
            raise VisualInertialLocalizationError("VIO sample has an invalid pose")
        values = np.asarray([*position, *quaternion], dtype=np.float64)
        if not np.all(np.isfinite(values)):
            raise VisualInertialLocalizationError("VIO sample contains a non-finite value")
        q_norm = float(np.linalg.norm(values[3:]))
        if abs(q_norm - 1.0) > 0.02:
            raise VisualInertialLocalizationError("VIO quaternion is not normalized")
        normalized_q = tuple(float(value / q_norm) for value in values[3:])
        try:
            timestamp_ms = int(row["timestamp_ms"])
            confidence = float(row.get("confidence", 1.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise VisualInertialLocalizationError("VIO sample metadata is invalid") from exc
        if timestamp_ms < 0 or not 0.0 <= confidence <= 1.0:
            raise VisualInertialLocalizationError("VIO sample metadata is outside valid bounds")
        # Progress 360's reconstruction plane stores forward as x and left as
        # y; z remains physical height in metres.
        samples.append(
            SfMPathSample(
                timestamp_ms=timestamp_ms,
                x=float(values[0]),
                y=float(values[1]),
                relative_z=float(values[2]),
                heading_deg=_heading_from_quaternion(normalized_q),
                confidence=confidence,
                orientation_q=normalized_q,
            )
        )
    return samples


def validate_visual_inertial_path(
    samples: list[SfMPathSample], *, end_timestamp_ms: int
) -> VisualInertialQuality:
    if len(samples) < 3:
        raise VisualInertialLocalizationError("VIO returned fewer than three poses")
    timestamps = [sample.timestamp_ms for sample in samples]
    if timestamps != sorted(set(timestamps)):
        raise VisualInertialLocalizationError("VIO timestamps are not strictly increasing")
    if timestamps[0] > MAXIMUM_SAMPLE_GAP_MS:
        raise VisualInertialLocalizationError("VIO trajectory does not cover the capture start")
    coverage = min(1.0, timestamps[-1] / max(1, end_timestamp_ms))
    if coverage < MINIMUM_COVERAGE_RATIO:
        raise VisualInertialLocalizationError(
            f"VIO trajectory covers only {coverage:.1%} of the capture"
        )

    path_length = 0.0
    maximum_speed = 0.0
    maximum_gap = 0
    for previous, current in zip(samples, samples[1:], strict=False):
        gap_ms = current.timestamp_ms - previous.timestamp_ms
        maximum_gap = max(maximum_gap, gap_ms)
        if gap_ms <= 0:
            raise VisualInertialLocalizationError("VIO trajectory contains an invalid time step")
        distance = math.dist(
            (previous.x, previous.y, previous.relative_z),
            (current.x, current.y, current.relative_z),
        )
        path_length += distance
        maximum_speed = max(maximum_speed, distance / (gap_ms / 1000.0))
    if maximum_gap > MAXIMUM_SAMPLE_GAP_MS:
        raise VisualInertialLocalizationError(
            f"VIO trajectory contains a {maximum_gap} ms tracking gap"
        )
    if path_length < MINIMUM_PATH_LENGTH_M:
        raise VisualInertialLocalizationError("VIO trajectory has no credible translation")
    if maximum_speed > MAXIMUM_WALKING_SPEED_M_S:
        raise VisualInertialLocalizationError(
            f"VIO trajectory implies {maximum_speed:.2f} m/s walking speed"
        )
    return VisualInertialQuality(
        coverage_ratio=coverage,
        path_length_m=path_length,
        maximum_speed_m_s=maximum_speed,
        maximum_gap_ms=maximum_gap,
    )


def recover_visual_inertial_path(
    video_source: Path,
    *,
    sensor_source: Path | None,
    end_timestamp_ms: int,
) -> list[SfMPathSample]:
    settings = get_settings()
    runner = Path(settings.visual_inertial_runner_path or "")
    calibration = Path(settings.visual_inertial_calibration_path or "")
    if sensor_source is None or sensor_source.suffix.lower() != ".insv":
        raise VisualInertialLocalizationError(
            "Metric VIO requires the original INSV alongside the stitched video"
        )
    if not runner.is_file():
        raise VisualInertialLocalizationError("VISUAL_INERTIAL_RUNNER_PATH is not configured")
    if not calibration.is_file():
        raise VisualInertialLocalizationError(
            "Camera-to-IMU calibration is missing; refusing an uncalibrated trajectory"
        )

    with temporary_workspace(prefix="progress-vio-") as temporary:
        output = Path(temporary) / "trajectory.json"
        command = [
            *([sys.executable, str(runner)] if runner.suffix.lower() == ".py" else [str(runner)]),
            "--video",
            str(video_source),
            "--insv",
            str(sensor_source),
            "--calibration",
            str(calibration),
            "--output",
            str(output),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=settings.visual_inertial_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VisualInertialLocalizationError("VIO runner could not complete") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error")[-1500:]
            raise VisualInertialLocalizationError(f"VIO runner failed: {detail}")
        samples = _parse_trajectory(output)
        validate_visual_inertial_path(samples, end_timestamp_ms=end_timestamp_ms)
        return samples
