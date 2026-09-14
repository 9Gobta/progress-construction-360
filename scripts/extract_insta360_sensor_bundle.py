"""Extract the timestamped X5 IMU stream without modifying the source INSV."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import telemetry_parser


def extract_sensor_bundle(source: Path) -> dict[str, object]:
    parser = telemetry_parser.Parser(str(source))
    rows = parser.normalized_imu()
    samples: list[dict[str, object]] = []
    previous_timestamp: float | None = None
    gaps: list[float] = []
    for row in rows:
        timestamp_ms = float(row["timestamp_ms"])
        gyro = [float(value) for value in row["gyro"]]
        acceleration = [float(value) for value in row["accl"]]
        if not all(math.isfinite(value) for value in [timestamp_ms, *gyro, *acceleration]):
            raise ValueError("INSV contains a non-finite IMU sample")
        if previous_timestamp is not None:
            gap = timestamp_ms - previous_timestamp
            if gap <= 0:
                raise ValueError("INSV IMU timestamps are not strictly increasing")
            gaps.append(gap)
        previous_timestamp = timestamp_ms
        samples.append(
            {
                "timestamp_ms": timestamp_ms,
                "angular_velocity": gyro,
                "linear_acceleration": acceleration,
            }
        )
    if len(samples) < 2:
        raise ValueError("INSV does not contain enough IMU samples")
    median_gap = sorted(gaps)[len(gaps) // 2]
    return {
        "schema": "progress360-insta360-imu-v1",
        "source_filename": source.name,
        # telemetry-parser exposes normalized Insta360 values. Axis alignment
        # is intentionally not guessed here; it belongs to the per-camera
        # calibration consumed by the VIO runner.
        "axis_frame": "insta360-normalized-uncalibrated",
        "timestamp_unit": "millisecond",
        "sample_count": len(samples),
        "median_sample_rate_hz": 1000.0 / median_gap,
        "maximum_gap_ms": max(gaps),
        "samples": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.source.suffix.lower() != ".insv" or not args.source.is_file():
        raise SystemExit("source must be an existing .insv file")
    payload = extract_sensor_bundle(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(f"{args.output.suffix}.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(args.output)
    print(
        json.dumps(
            {key: payload[key] for key in ("sample_count", "median_sample_rate_hz", "maximum_gap_ms")}
        )
    )


if __name__ == "__main__":
    main()
