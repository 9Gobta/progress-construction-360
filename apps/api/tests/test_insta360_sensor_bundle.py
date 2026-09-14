from types import SimpleNamespace

import pytest
from scripts import extract_insta360_sensor_bundle as sensor_bundle


def test_extract_sensor_bundle_preserves_timestamped_gyro_and_acceleration(monkeypatch) -> None:
    rows = [
        {"timestamp_ms": 0.0, "gyro": [1, 2, 3], "accl": [4, 5, 6]},
        {"timestamp_ms": 1.0, "gyro": [2, 3, 4], "accl": [5, 6, 7]},
        {"timestamp_ms": 2.0, "gyro": [3, 4, 5], "accl": [6, 7, 8]},
    ]
    monkeypatch.setattr(
        sensor_bundle.telemetry_parser,
        "Parser",
        lambda _source: SimpleNamespace(normalized_imu=lambda: rows),
    )

    payload = sensor_bundle.extract_sensor_bundle(sensor_bundle.Path("capture.insv"))

    assert payload["axis_frame"] == "insta360-normalized-uncalibrated"
    assert payload["sample_count"] == 3
    assert payload["median_sample_rate_hz"] == pytest.approx(1_000.0)
    assert payload["maximum_gap_ms"] == pytest.approx(1.0)
    assert payload["samples"][1]["angular_velocity"] == [2.0, 3.0, 4.0]


def test_extract_sensor_bundle_rejects_duplicate_timestamps(monkeypatch) -> None:
    rows = [
        {"timestamp_ms": 1.0, "gyro": [1, 2, 3], "accl": [4, 5, 6]},
        {"timestamp_ms": 1.0, "gyro": [2, 3, 4], "accl": [5, 6, 7]},
    ]
    monkeypatch.setattr(
        sensor_bundle.telemetry_parser,
        "Parser",
        lambda _source: SimpleNamespace(normalized_imu=lambda: rows),
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        sensor_bundle.extract_sensor_bundle(sensor_bundle.Path("capture.insv"))
