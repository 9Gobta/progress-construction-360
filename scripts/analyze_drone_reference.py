"""Build a georeference summary from DJI photos and a RealityScan camera CSV."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image


def _degrees(value: tuple[float, float, float], reference: str) -> float:
    result = float(value[0]) + float(value[1]) / 60.0 + float(value[2]) / 3600.0
    return -result if reference in {"S", "W"} else result


def _gps(path: Path) -> tuple[float, float, float] | None:
    with Image.open(path) as image:
        gps = image.getexif().get_ifd(34853)
    if not gps:
        return None
    named = {ExifTags.GPSTAGS.get(key, key): value for key, value in gps.items()}
    return (
        _degrees(named["GPSLatitude"], named["GPSLatitudeRef"]),
        _degrees(named["GPSLongitude"], named["GPSLongitudeRef"]),
        float(named.get("GPSAltitude", 0.0)),
    )


def _xmp_float(path: Path, name: str) -> float | None:
    payload = path.read_bytes()
    match = re.search(rb"drone-dji:" + name.encode() + rb'=\"([+-]?[0-9.]+)\"', payload)
    return float(match.group(1)) if match else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--radius-m", type=float, default=350.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    camera_csv = args.root / "SS.csv"
    with camera_csv.open(encoding="utf-8-sig") as handle:
        reality = {row["#name"]: row for row in csv.DictReader(handle)}

    records: list[dict[str, object]] = []
    for path in sorted(args.root.glob("DJI_*.JPG")):
        gps = _gps(path)
        if gps is None:
            continue
        latitude, longitude, altitude = gps
        north = (latitude - args.latitude) * 110_540.0
        east = (
            (longitude - args.longitude)
            * 111_320.0
            * math.cos(math.radians(args.latitude))
        )
        distance = math.hypot(east, north)
        if distance > args.radius_m:
            continue
        record: dict[str, object] = {
            "name": path.name,
            "latitude": latitude,
            "longitude": longitude,
            "gps_altitude_m": altitude,
            "east_m": east,
            "north_m": north,
            "distance_to_site_m": distance,
            "gimbal_yaw_deg": _xmp_float(path, "GimbalYawDegree"),
            "gimbal_pitch_deg": _xmp_float(path, "GimbalPitchDegree"),
        }
        if path.name in reality:
            row = reality[path.name]
            record.update(
                reality_x=float(row["x"]),
                reality_y=float(row["y"]),
                reality_z=float(row["alt"]),
                reality_yaw_deg=float(row["yaw"]),
                reality_pitch_deg=float(row["pitch"]),
            )
        records.append(record)

    matched = [record for record in records if "reality_x" in record]
    if len(matched) < 3:
        raise SystemExit("Need at least three site photos present in SS.csv")
    source = np.array(
        [[record["reality_x"], record["reality_y"], 1.0] for record in matched],
        dtype=float,
    )
    target = np.array(
        [[record["east_m"], record["north_m"]] for record in matched],
        dtype=float,
    )
    affine, *_ = np.linalg.lstsq(source, target, rcond=None)
    predicted = source @ affine
    residuals = np.linalg.norm(predicted - target, axis=1)
    result = {
        "site_wgs84": {"latitude": args.latitude, "longitude": args.longitude},
        "photo_count_near_site": len(records),
        "reality_camera_count": len(matched),
        "oblique_camera_count": sum(
            1
            for record in matched
            if record["gimbal_pitch_deg"] is not None
            and float(record["gimbal_pitch_deg"]) > -75.0
        ),
        "reality_xy_to_site_enu_affine": affine.tolist(),
        "gps_fit_rmse_m": float(np.sqrt(np.mean(residuals**2))),
        "gps_fit_median_m": float(np.median(residuals)),
        "gps_fit_p95_m": float(np.percentile(residuals, 95)),
        "photos": records,
    }
    output = args.output or args.root / "drone-reference.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "photos"}, indent=2))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
