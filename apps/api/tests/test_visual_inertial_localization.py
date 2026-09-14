import json
from types import SimpleNamespace

import pytest

from progress_api.services.visual_inertial_localization import (
    VisualInertialLocalizationError,
    _heading_from_quaternion,
    _parse_trajectory,
    recover_visual_inertial_path,
    validate_visual_inertial_path,
)


def _write_trajectory(path, samples, **overrides):
    payload = {
        "schema": "progress360-vio-trajectory-v1",
        "coordinate_frame": "x-forward_y-left_z-up",
        "position_unit": "metre",
        "samples": samples,
        **overrides,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sample(timestamp_ms: int, x: float, *, quaternion=None):
    return {
        "timestamp_ms": timestamp_ms,
        "position_m": [x, 0.0, 1.65],
        "camera_to_world_xyzw": quaternion or [0.0, 2**-0.5, 0.0, 2**-0.5],
        "confidence": 0.95,
    }


def test_metric_vio_trajectory_passes_physical_quality_gate(tmp_path) -> None:
    output = tmp_path / "trajectory.json"
    _write_trajectory(
        output,
        [
            _sample(0, 0.0, quaternion=[0.0, 2**-0.5, 0.0, 2**-0.5]),
            _sample(1_000, 0.8, quaternion=[0.0, 2**-0.5, 0.0, 2**-0.5]),
            _sample(2_000, 1.6, quaternion=[0.0, 2**-0.5, 0.0, 2**-0.5]),
        ],
    )

    samples = _parse_trajectory(output)
    quality = validate_visual_inertial_path(samples, end_timestamp_ms=2_000)

    assert quality.coverage_ratio == 1.0
    assert quality.path_length_m == pytest.approx(1.6)
    assert quality.maximum_speed_m_s == pytest.approx(0.8)
    assert samples[0].heading_deg == pytest.approx(0.0)


def test_heading_uses_panorama_forward_axis_not_quaternion_euler_yaw() -> None:
    # -90 degrees around camera X maps its local +Z centre ray to world +Y.
    half = 2**-0.5
    assert _heading_from_quaternion((-half, 0.0, 0.0, half)) == pytest.approx(90.0)


def test_vio_rejects_non_metric_or_ambiguous_coordinate_output(tmp_path) -> None:
    output = tmp_path / "trajectory.json"
    _write_trajectory(
        output,
        [_sample(0, 0.0), _sample(1_000, 1.0), _sample(2_000, 2.0)],
        position_unit="arbitrary",
    )

    with pytest.raises(VisualInertialLocalizationError, match="must be metric"):
        _parse_trajectory(output)


def test_vio_rejects_partial_tracking_instead_of_extrapolating(tmp_path) -> None:
    output = tmp_path / "trajectory.json"
    _write_trajectory(
        output,
        [_sample(0, 0.0), _sample(500, 0.4), _sample(1_000, 0.8)],
    )

    samples = _parse_trajectory(output)
    with pytest.raises(VisualInertialLocalizationError, match="covers only"):
        validate_visual_inertial_path(samples, end_timestamp_ms=10_000)


def test_vio_rejects_implausible_jump(tmp_path) -> None:
    output = tmp_path / "trajectory.json"
    _write_trajectory(
        output,
        [_sample(0, 0.0), _sample(500, 0.2), _sample(1_000, 10.0)],
    )

    samples = _parse_trajectory(output)
    with pytest.raises(VisualInertialLocalizationError, match="walking speed"):
        validate_visual_inertial_path(samples, end_timestamp_ms=1_000)


def test_vio_runner_receives_video_insv_calibration_and_returns_metric_path(
    monkeypatch, tmp_path
) -> None:
    video = tmp_path / "stitched.mp4"
    sensor = tmp_path / "source.insv"
    calibration = tmp_path / "camera-imu.yaml"
    runner = tmp_path / "runner.py"
    for path in (video, sensor, calibration):
        path.write_bytes(b"fixture")
    payload = {
        "schema": "progress360-vio-trajectory-v1",
        "coordinate_frame": "x-forward_y-left_z-up",
        "position_unit": "metre",
        "samples": [
            _sample(0, 0.0),
            _sample(1_000, 0.8),
            _sample(2_000, 1.6),
        ],
    }
    runner.write_text(
        "import argparse, json\n"
        "p=argparse.ArgumentParser()\n"
        "p.add_argument('--video')\n"
        "p.add_argument('--insv')\n"
        "p.add_argument('--calibration')\n"
        "p.add_argument('--output')\n"
        "a=p.parse_args()\n"
        f"open(a.output, 'w', encoding='utf-8').write(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "progress_api.services.visual_inertial_localization.get_settings",
        lambda: SimpleNamespace(
            visual_inertial_runner_path=str(runner),
            visual_inertial_calibration_path=str(calibration),
            visual_inertial_timeout_seconds=60,
        ),
    )

    samples = recover_visual_inertial_path(
        video,
        sensor_source=sensor,
        end_timestamp_ms=2_000,
    )

    assert len(samples) == 3
    assert samples[-1].x == pytest.approx(1.6)
