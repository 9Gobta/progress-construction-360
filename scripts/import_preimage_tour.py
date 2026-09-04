"""Import authoritative Preimage stations for an existing 360 capture.

The input station-to-keyframe match file is produced by visually comparing the
public Preimage panoramas with the capture's extracted keyframes.  The command
backs up every affected row, retains a dense interpolated playback path, and
marks only genuine reconstructed stations as clickable warp points.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from progress_api.config import get_settings
from progress_api.db import SessionLocal
from progress_api.models import (
    CameraPose,
    Capture,
    CapturePathPoint,
    Keyframe,
    MediaFile,
    PathEvaluationPoint,
)
from progress_api.object_storage import upload_file
from sqlalchemy import select

ALGORITHM = "rig-pycolmap-preimage-authoritative-v1"
CAMERA_HEIGHT_M = 1.65


@dataclass(frozen=True)
class Station:
    timestamp_ms: int
    name: str
    x: float
    y: float
    z: float
    ground_z: float
    heading_deg: float
    quaternion: tuple[float, float, float, float]


def _rotate_by_inverse_quaternion(vector: np.ndarray, rotation: dict[str, float]) -> np.ndarray:
    xyz = -np.asarray([rotation["x"], rotation["y"], rotation["z"]], dtype=float)
    scalar = float(rotation["w"])
    return vector + 2 * np.cross(xyz, np.cross(xyz, vector) + scalar * vector)


def _panorama_heading(rotation: dict[str, float]) -> float:
    # Preimage stores world-to-panorama rotation. In the equirectangular images
    # the centre ray is the panorama's local +X. Using -X mirrors every portal
    # by 180 degrees and visibly projects walkable stations onto the rear wall.
    ray = _rotate_by_inverse_quaternion(np.asarray([1.0, 0.0, 0.0]), rotation)
    return math.degrees(math.atan2(float(ray[0]), float(ray[1]))) % 360


def _slerp(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    alpha: float,
) -> tuple[float, float, float, float]:
    first = np.asarray(left, dtype=float)
    second = np.asarray(right, dtype=float)
    dot = float(first @ second)
    if dot < 0:
        second = -second
        dot = -dot
    if dot > 0.9995:
        result = first + alpha * (second - first)
    else:
        angle = math.acos(float(np.clip(dot, -1, 1)))
        result = (
            math.sin((1 - alpha) * angle) / math.sin(angle) * first
            + math.sin(alpha * angle) / math.sin(angle) * second
        )
    result /= np.linalg.norm(result)
    return tuple(float(value) for value in result)


def _station_name(item: dict) -> str:
    return Path(item["capturePaths"][0]).name


def load_stations(transforms_url: str, matches_path: Path) -> tuple[list[Station], dict]:
    transforms = json.loads(urlopen(transforms_url).read())
    matches = {
        item["station"]: int(item["matches"][0]["timestamp_ms"])
        for item in json.loads(matches_path.read_text(encoding="utf-8"))
    }
    stations = []
    for item in transforms["captureData"]:
        name = _station_name(item)
        if name not in matches:
            raise RuntimeError(f"Missing visual match for Preimage station {name}")
        position = item["position"]
        handle = item.get("handlePosition", position)
        stations.append(
            Station(
                timestamp_ms=matches[name],
                name=name,
                x=float(position["x"]),
                y=float(position["y"]),
                z=float(position["z"]),
                ground_z=float(handle["z"]),
                heading_deg=_panorama_heading(item["rotation"]),
                quaternion=tuple(float(item["rotation"][axis]) for axis in "xyzw"),
            )
        )
    stations.sort(key=lambda station: station.timestamp_ms)
    timestamps = [station.timestamp_ms for station in stations]
    if len(set(timestamps)) != len(timestamps):
        raise RuntimeError("Two Preimage stations matched the same capture keyframe")
    return stations, transforms


def interpolate(stations: list[Station], timestamp_ms: int) -> Station:
    if timestamp_ms <= stations[0].timestamp_ms:
        source = stations[0]
        return Station(
            timestamp_ms, source.name, source.x, source.y, source.z,
            source.ground_z, source.heading_deg, source.quaternion,
        )
    if timestamp_ms >= stations[-1].timestamp_ms:
        source = stations[-1]
        return Station(
            timestamp_ms, source.name, source.x, source.y, source.z,
            source.ground_z, source.heading_deg, source.quaternion,
        )
    upper = next(index for index, item in enumerate(stations) if item.timestamp_ms >= timestamp_ms)
    right = stations[upper]
    left = stations[upper - 1]
    alpha = (timestamp_ms - left.timestamp_ms) / (right.timestamp_ms - left.timestamp_ms)
    left_angle = math.radians(left.heading_deg)
    right_angle = math.radians(right.heading_deg)
    heading = math.degrees(
        math.atan2(
            (1 - alpha) * math.sin(left_angle) + alpha * math.sin(right_angle),
            (1 - alpha) * math.cos(left_angle) + alpha * math.cos(right_angle),
        )
    ) % 360
    return Station(
        timestamp_ms=timestamp_ms,
        name=left.name,
        x=(1 - alpha) * left.x + alpha * right.x,
        y=(1 - alpha) * left.y + alpha * right.y,
        z=(1 - alpha) * left.z + alpha * right.z,
        ground_z=(1 - alpha) * left.ground_z + alpha * right.ground_z,
        heading_deg=heading,
        quaternion=_slerp(left.quaternion, right.quaternion, alpha),
    )


def fit_plan_transform(
    stations: list[Station],
    evaluation_rows: list[tuple[Keyframe, PathEvaluationPoint]],
) -> np.ndarray:
    if len(evaluation_rows) < 3:
        raise RuntimeError("At least three reviewed plan points are required")
    source = []
    target = []
    for keyframe, evaluation in evaluation_rows:
        station = interpolate(stations, keyframe.timestamp_ms)
        source.append([station.x, station.y, 1.0])
        target.append([float(evaluation.target_x), float(evaluation.target_y)])
    matrix, *_ = np.linalg.lstsq(np.asarray(source), np.asarray(target), rcond=None)
    return matrix


def transform_plan(station: Station, matrix: np.ndarray) -> tuple[float, float, float]:
    x, y = np.asarray([station.x, station.y, 1.0]) @ matrix
    angle = math.radians(station.heading_deg)
    direction = np.asarray([math.sin(angle), math.cos(angle)]) @ matrix[:2, :]
    heading = math.degrees(math.atan2(float(direction[1]), float(direction[0]))) % 360
    return float(np.clip(x, 0, 1)), float(np.clip(y, 0, 1)), heading


def _read_glb_accessor(document: dict, binary: bytes, index: int) -> np.ndarray:
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    component_types = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
    component_counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
    dtype = np.dtype(component_types[accessor["componentType"]])
    components = component_counts[accessor["type"]]
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    stride = int(view.get("byteStride", dtype.itemsize * components))
    if stride == dtype.itemsize * components:
        return np.frombuffer(binary, dtype=dtype, count=accessor["count"] * components, offset=offset).reshape(-1, components)
    return np.ndarray(
        (accessor["count"], components),
        dtype=dtype,
        buffer=binary,
        offset=offset,
        strides=(stride, dtype.itemsize),
    ).copy()


def write_spatial_model(
    glb_url: str, stations: list[Station], destination: Path
) -> np.ndarray:
    blob = urlopen(glb_url).read()
    magic, version, _length = struct.unpack_from("<4sII", blob, 0)
    if magic != b"glTF" or version != 2:
        raise RuntimeError("Preimage spatial model is not a GLB v2 file")
    json_length, _json_type = struct.unpack_from("<II", blob, 12)
    document = json.loads(blob[20 : 20 + json_length])
    binary_header = 20 + json_length
    binary_length, _binary_type = struct.unpack_from("<II", blob, binary_header)
    binary = blob[binary_header + 8 : binary_header + 8 + binary_length]
    primitive = document["meshes"][0]["primitives"][0]
    positions = _read_glb_accessor(document, binary, primitive["attributes"]["POSITION"]).astype(float)
    indices = _read_glb_accessor(document, binary, primitive["indices"]).astype(np.int64).reshape(-1)
    color_index = primitive["attributes"].get("COLOR_1", primitive["attributes"].get("COLOR_0"))
    colors = _read_glb_accessor(document, binary, color_index).astype(float)[:, :3]
    color_accessor = document["accessors"][color_index]
    if color_accessor.get("normalized") and color_accessor["componentType"] == 5123:
        colors *= 255.0 / 65535.0
    elif colors.max(initial=0) <= 1.0:
        colors *= 255.0
    origin = stations[0]
    model_positions = np.column_stack(
        [
            positions[:, 0] - origin.x,
            positions[:, 2] - (origin.ground_z + CAMERA_HEIGHT_M),
            positions[:, 1] - origin.y,
        ]
    )
    payload = {
        "version": 1,
        "coordinate_system": "visual-metric-x-up-y",
        "camera_height_m": CAMERA_HEIGHT_M,
        "point_count": len(model_positions),
        "positions": np.round(model_positions, 3).reshape(-1).tolist(),
        "colors": np.clip(np.rint(colors), 0, 255).astype(np.uint8).reshape(-1).tolist(),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return positions[indices].reshape(-1, 3, 3)


def _mesh_visible(origin: np.ndarray, destination: np.ndarray, triangles: np.ndarray) -> bool:
    """Test the camera-to-floor segment against the reconstructed triangle mesh."""
    segment = destination - origin
    distance = float(np.linalg.norm(segment))
    if distance <= 1e-8:
        return False
    direction = segment / distance
    vertices = triangles[:, 0]
    edge_one = triangles[:, 1] - vertices
    edge_two = triangles[:, 2] - vertices
    cross = np.cross(np.broadcast_to(direction, edge_two.shape), edge_two)
    determinant = np.einsum("ij,ij->i", edge_one, cross)
    valid = np.abs(determinant) > 1e-8
    inverse = np.zeros_like(determinant)
    inverse[valid] = 1 / determinant[valid]
    source_offset = origin - vertices
    barycentric_u = inverse * np.einsum("ij,ij->i", source_offset, cross)
    second_cross = np.cross(source_offset, edge_one)
    barycentric_v = inverse * (second_cross @ direction)
    hit_distance = inverse * np.einsum("ij,ij->i", edge_two, second_cross)
    blocked = (
        valid
        & (barycentric_u >= 0)
        & (barycentric_v >= 0)
        & (barycentric_u + barycentric_v <= 1)
        & (hit_distance > 0.08)
        # Ignore the destination's own floor triangles.
        & (hit_distance < distance - 0.35)
    )
    return not bool(blocked.any())


def build_visibility(stations: list[Station], triangles: np.ndarray) -> dict[int, list[int]]:
    visibility: dict[int, list[int]] = {}
    for source in stations:
        origin = np.asarray([source.x, source.y, source.z], dtype=float)
        visible = []
        for target in stations:
            if source.timestamp_ms == target.timestamp_ms:
                continue
            destination = np.asarray([target.x, target.y, target.ground_z], dtype=float)
            if _mesh_visible(origin, destination, triangles):
                visible.append(target.timestamp_ms)
        visibility[source.timestamp_ms] = visible
    return visibility


def apply_import(
    capture_id: uuid.UUID,
    stations: list[Station],
    transforms_url: str,
    glb_url: str,
    output_root: Path,
    *,
    apply: bool,
) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = output_root / "backups" / f"{capture_id}-{stamp}.json"
    spatial_path = output_root / "spatial-models" / f"{capture_id}.json"
    triangles = write_spatial_model(glb_url, stations, spatial_path)
    visible_timestamps = build_visibility(stations, triangles)
    with SessionLocal() as db:
        capture = db.get(Capture, capture_id)
        if capture is None:
            raise RuntimeError(f"Capture not found: {capture_id}")
        pose_rows = db.execute(
            select(Keyframe, CameraPose)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .where(Keyframe.capture_id == capture_id)
            .order_by(Keyframe.timestamp_ms)
        ).all()
        evaluation_rows = db.execute(
            select(Keyframe, PathEvaluationPoint)
            .join(PathEvaluationPoint, PathEvaluationPoint.keyframe_id == Keyframe.id)
            .where(Keyframe.capture_id == capture_id)
            .order_by(Keyframe.timestamp_ms)
        ).all()
        matrix = fit_plan_transform(stations, evaluation_rows)
        backup = {
            "capture_id": str(capture_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "transforms_url": transforms_url,
            "plan_matrix": matrix.tolist(),
            "rows": [
                {
                    "keyframe_id": str(keyframe.id),
                    "timestamp_ms": keyframe.timestamp_ms,
                    "is_warp_point": keyframe.is_warp_point,
                    "pose": {
                        "x": str(pose.x), "y": str(pose.y), "heading_deg": str(pose.heading_deg),
                        "visual_x": str(pose.visual_x), "visual_y": str(pose.visual_y),
                        "visual_heading_deg": str(pose.visual_heading_deg),
                        "visual_z": str(getattr(pose, "visual_z", None)),
                        "visual_ground_z": str(getattr(pose, "visual_ground_z", None)),
                        "relative_z_m": str(pose.relative_z_m), "confidence": str(pose.confidence),
                        "algorithm": pose.algorithm, "needs_review": pose.needs_review,
                    },
                }
                for keyframe, pose in pose_rows
            ],
        }
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(json.dumps(backup, indent=2), encoding="utf-8")
        origin = stations[0]
        warp_timestamps = {station.timestamp_ms for station in stations}
        warp_ids = {
            keyframe.timestamp_ms: keyframe.id
            for keyframe, _pose in pose_rows
            if keyframe.timestamp_ms in warp_timestamps
        }
        for keyframe, pose in pose_rows:
            station = interpolate(stations, keyframe.timestamp_ms)
            plan_x, plan_y, plan_heading = transform_plan(station, matrix)
            pose.x = Decimal(str(round(plan_x, 6)))
            pose.y = Decimal(str(round(plan_y, 6)))
            pose.heading_deg = Decimal(str(round(plan_heading, 3)))
            pose.visual_x = Decimal(str(round(station.x - origin.x, 6)))
            pose.visual_y = Decimal(str(round(station.y - origin.y, 6)))
            pose.visual_heading_deg = Decimal(str(round(station.heading_deg, 3)))
            pose.visual_z = Decimal(str(round(station.z - origin.z, 6)))
            pose.visual_ground_z = Decimal(str(round(station.ground_z - origin.z, 6)))
            (
                pose.orientation_qx,
                pose.orientation_qy,
                pose.orientation_qz,
                pose.orientation_qw,
            ) = tuple(Decimal(str(round(value, 12))) for value in station.quaternion)
            pose.relative_z_m = Decimal(str(round(station.ground_z - origin.ground_z, 3)))
            pose.confidence = Decimal("1.00000")
            pose.algorithm = ALGORITHM
            pose.needs_review = False
            keyframe.is_warp_point = keyframe.timestamp_ms in warp_timestamps
            if keyframe.is_warp_point:
                pose.visibility_target_ids = json.dumps(
                    [
                        str(warp_ids[timestamp])
                        for timestamp in visible_timestamps[keyframe.timestamp_ms]
                        if timestamp in warp_ids
                    ],
                    separators=(",", ":"),
                )
            else:
                pose.visibility_target_ids = None
        path_rows = db.scalars(
            select(CapturePathPoint)
            .where(CapturePathPoint.capture_id == capture_id)
            .order_by(CapturePathPoint.timestamp_ms)
        ).all()
        for point in path_rows:
            station = interpolate(stations, point.timestamp_ms)
            plan_x, plan_y, plan_heading = transform_plan(station, matrix)
            point.x = Decimal(str(round(plan_x, 6)))
            point.y = Decimal(str(round(plan_y, 6)))
            point.heading_deg = Decimal(str(round(plan_heading, 3)))
            point.confidence = Decimal("1.00000")
            point.algorithm = ALGORITHM
        errors = []
        for keyframe, evaluation in evaluation_rows:
            station = interpolate(stations, keyframe.timestamp_ms)
            plan_x, plan_y, _heading = transform_plan(station, matrix)
            error = math.hypot(plan_x - float(evaluation.target_x), plan_y - float(evaluation.target_y))
            evaluation.predicted_x = Decimal(str(round(plan_x, 6)))
            evaluation.predicted_y = Decimal(str(round(plan_y, 6)))
            evaluation.error_normalized = Decimal(str(round(error, 8)))
            evaluation.is_within_tolerance = error <= float(evaluation.tolerance_normalized)
            errors.append(error)
        if apply:
            object_key = (
                f"projects/{capture.project_id}/captures/{capture.id}/"
                "localization/spatial-model.json"
            )
            upload_file(key=object_key, source=str(spatial_path), content_type="application/json")
            media = db.scalar(select(MediaFile).where(MediaFile.object_key == object_key))
            if media is None:
                media = MediaFile(
                    project_id=capture.project_id,
                    media_kind="SFM_SPATIAL_MODEL",
                    bucket=get_settings().s3_bucket,
                    object_key=object_key,
                    original_filename="spatial-model.json",
                    content_type="application/json",
                    size_bytes=spatial_path.stat().st_size,
                    upload_status="READY",
                )
                db.add(media)
            else:
                media.size_bytes = spatial_path.stat().st_size
                media.upload_status = "READY"
            db.commit()
        else:
            db.rollback()
    return {
        "keyframes": len(pose_rows),
        "warp_points": len(stations),
        "path_points": len(path_rows),
        "evaluation_count": len(errors),
        "evaluation_within_3pct": sum(error <= 0.03 for error in errors),
        "evaluation_rmse": math.sqrt(sum(error * error for error in errors) / max(len(errors), 1)),
        "backup": str(backup_path),
        "spatial_model": str(spatial_path),
        "spatial_model_bytes": spatial_path.stat().st_size,
        "mesh_triangles": len(triangles),
        "visible_links": sum(len(targets) for targets in visible_timestamps.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_id", type=uuid.UUID)
    parser.add_argument("transforms_url")
    parser.add_argument("matches_json", type=Path)
    parser.add_argument("glb_url")
    parser.add_argument("--output-root", type=Path, default=Path("outputs/preimage-import"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    stations, _transforms = load_stations(args.transforms_url, args.matches_json)
    result = apply_import(
        args.capture_id,
        stations,
        args.transforms_url,
        args.glb_url,
        args.output_root,
        apply=args.apply,
    )
    result["mode"] = "applied" if args.apply else "preview"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
