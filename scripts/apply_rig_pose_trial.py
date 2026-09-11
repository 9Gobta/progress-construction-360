"""Apply a rig-constrained SfM trajectory to one trial Capture.

The command is deliberately opt-in and always writes a JSON backup before it
changes application data.  Absolute floor-plan coordinates are not touched;
the learned trajectory remains review-required until it is aligned to real
plan control points.
"""

from __future__ import annotations

import argparse
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pycolmap
from progress_api.config import get_settings
from progress_api.db import SessionLocal
from progress_api.models import CameraPose, Capture, Keyframe, MediaFile
from progress_api.object_storage import upload_file
from progress_api.services.sfm_localization import (
    CAMERA_HEIGHT_M,
    _estimate_camera_height,
    _write_spatial_model,
)
from progress_api.services.video_pipeline import (
    TourStationSample,
    select_spatial_warp_points,
)
from sqlalchemy import select

DEFAULT_ALGORITHM = "hloc-rig-disk-lightglue-poc-v1"


@dataclass(frozen=True)
class RigPose:
    timestamp_ms: int
    x: float
    y: float
    z: float
    heading_deg: float


def _reference_image(model: pycolmap.Reconstruction, frame: pycolmap.Frame):
    images = [model.images[data_id.id] for data_id in frame.data_ids]
    return min(images, key=lambda image: int(Path(image.name).parts[0]))


def load_rig_trajectory(
    model_path: Path, spatial_model_output: Path | None = None
) -> list[RigPose]:
    model = pycolmap.Reconstruction(model_path)
    samples: list[tuple[int, np.ndarray, np.ndarray, np.ndarray]] = []
    for frame in model.frames.values():
        if not frame.has_pose:
            continue
        image = _reference_image(model, frame)
        timestamp_ms = int(Path(image.name).stem.split("_")[-1])
        centre = np.asarray(image.projection_center(), dtype=np.float64)
        cam_from_world = image.cam_from_world()
        world_from_camera_rotation = cam_from_world.rotation.matrix().T
        forward = world_from_camera_rotation @ np.asarray(
            [0.0, 0.0, 1.0], dtype=np.float64
        )
        camera_up = world_from_camera_rotation @ np.asarray(
            [0.0, -1.0, 0.0], dtype=np.float64
        )
        samples.append((timestamp_ms, centre, forward, camera_up))
    samples.sort(key=lambda sample: sample[0])
    if len(samples) < 2:
        raise RuntimeError("Rig model does not contain a usable trajectory")

    centres = np.stack([sample[1] for sample in samples])
    origin = centres[0]
    up_reference = samples[0][3]
    aligned_up = [
        up if float(np.dot(up, up_reference)) >= 0 else -up
        for _timestamp, _centre, _forward, up in samples
    ]
    vertical = np.mean(np.stack(aligned_up), axis=0)
    vertical /= max(float(np.linalg.norm(vertical)), 1e-9)
    centred = centres - origin
    horizontal = centred - np.outer(centred @ vertical, vertical)
    _u, _singular_values, axes = np.linalg.svd(horizontal, full_matrices=False)
    axis_x = axes[0] - float(np.dot(axes[0], vertical)) * vertical
    axis_x /= max(float(np.linalg.norm(axis_x)), 1e-9)
    axis_y = np.cross(vertical, axis_x)
    axis_y /= max(float(np.linalg.norm(axis_y)), 1e-9)
    points = np.asarray(
        [point.xyz for point in model.points3D.values()], dtype=np.float64
    )
    camera_height = _estimate_camera_height(centres, points, vertical)
    metric_scale = CAMERA_HEIGHT_M / camera_height if camera_height else 1.0
    if spatial_model_output is not None:
        _write_spatial_model(
            model,
            spatial_model_output,
            origin=origin,
            axis_x=axis_x,
            axis_y=axis_y,
            vertical=vertical,
            metric_scale=metric_scale,
        )

    result: list[RigPose] = []
    for timestamp_ms, centre, forward, _up in samples:
        offset = centre - origin
        x = float(np.dot(offset, axis_x)) * metric_scale
        y = float(np.dot(offset, axis_y)) * metric_scale
        heading = math.degrees(
            math.atan2(float(np.dot(forward, axis_x)), float(np.dot(forward, axis_y)))
        ) % 360
        height = float(np.dot(offset, vertical)) * metric_scale
        result.append(
            RigPose(
                timestamp_ms=timestamp_ms,
                x=x,
                y=y,
                z=height,
                heading_deg=heading,
            )
        )
    coordinates = np.asarray([(pose.x, pose.y, pose.z) for pose in result])
    steps = np.linalg.norm(np.diff(coordinates, axis=0), axis=1)
    positive_steps = steps[steps > 1e-8]
    if not len(positive_steps):
        return result
    threshold = max(float(np.median(positive_steps)) * 6.0, 1e-6)
    rejected: set[int] = set()
    for index in range(1, len(result) - 1):
        left = float(np.linalg.norm(coordinates[index] - coordinates[index - 1]))
        right = float(np.linalg.norm(coordinates[index + 1] - coordinates[index]))
        bypass = float(
            np.linalg.norm(coordinates[index + 1] - coordinates[index - 1])
        )
        if left > threshold and right > threshold and bypass <= threshold * 2.0:
            rejected.add(index)
    return [pose for index, pose in enumerate(result) if index not in rejected]


def interpolate_pose(samples: list[RigPose], timestamp_ms: int) -> RigPose:
    if timestamp_ms <= samples[0].timestamp_ms:
        return samples[0]
    if timestamp_ms >= samples[-1].timestamp_ms:
        return samples[-1]
    upper = next(
        index
        for index, sample in enumerate(samples)
        if sample.timestamp_ms >= timestamp_ms
    )
    right = samples[upper]
    left = samples[upper - 1]
    span = right.timestamp_ms - left.timestamp_ms
    alpha = (timestamp_ms - left.timestamp_ms) / max(span, 1)
    left_angle = math.radians(left.heading_deg)
    right_angle = math.radians(right.heading_deg)
    heading = math.degrees(
        math.atan2(
            (1 - alpha) * math.sin(left_angle) + alpha * math.sin(right_angle),
            (1 - alpha) * math.cos(left_angle) + alpha * math.cos(right_angle),
        )
    ) % 360
    return RigPose(
        timestamp_ms=timestamp_ms,
        x=(1 - alpha) * left.x + alpha * right.x,
        y=(1 - alpha) * left.y + alpha * right.y,
        z=(1 - alpha) * left.z + alpha * right.z,
        heading_deg=heading,
    )


def apply_trial(
    capture_id: uuid.UUID,
    model_path: Path,
    backup_dir: Path,
    *,
    apply: bool,
    algorithm: str = DEFAULT_ALGORITHM,
) -> tuple[int, int, Path]:
    spatial_model_path = backup_dir.parent / "spatial-models" / f"{capture_id}.json"
    samples = load_rig_trajectory(model_path, spatial_model_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{capture_id}-{stamp}.json"

    with SessionLocal() as db:
        rows = db.execute(
            select(Keyframe, CameraPose)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .where(Keyframe.capture_id == capture_id)
            .order_by(Keyframe.timestamp_ms)
        ).all()
        if not rows:
            raise RuntimeError(f"No localized keyframes for Capture {capture_id}")
        backup = {
            "capture_id": str(capture_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model_path": str(model_path),
            "rows": [
                {
                    "keyframe_id": str(keyframe.id),
                    "timestamp_ms": keyframe.timestamp_ms,
                    "is_warp_point": keyframe.is_warp_point,
                    "visual_x": str(pose.visual_x) if pose.visual_x is not None else None,
                    "visual_y": str(pose.visual_y) if pose.visual_y is not None else None,
                    "visual_heading_deg": (
                        str(pose.visual_heading_deg)
                        if pose.visual_heading_deg is not None
                        else None
                    ),
                    "relative_z_m": (
                        str(pose.relative_z_m) if pose.relative_z_m is not None else None
                    ),
                    "confidence": str(pose.confidence),
                    "algorithm": pose.algorithm,
                    "needs_review": pose.needs_review,
                }
                for keyframe, pose in rows
            ],
        }
        backup_path.write_text(json.dumps(backup, indent=2), encoding="utf-8")

        learned_by_keyframe = {
            keyframe.id: interpolate_pose(samples, keyframe.timestamp_ms)
            for keyframe, _pose in rows
        }
        station_candidates = [
            TourStationSample(
                frame_index=keyframe.frame_index,
                timestamp_ms=keyframe.timestamp_ms,
                quality_status=keyframe.quality_status,
                x=learned_by_keyframe[keyframe.id].x,
                y=learned_by_keyframe[keyframe.id].y,
                heading_deg=learned_by_keyframe[keyframe.id].heading_deg,
            )
            for keyframe, _pose in rows
        ]
        selected_station_indices = select_spatial_warp_points(station_candidates)
        if len(selected_station_indices) < 2:
            selected_station_indices = {
                sample.frame_index for sample in station_candidates
            }
        warp_count = 0
        for keyframe, pose in rows:
            learned = learned_by_keyframe[keyframe.id]
            pose.visual_x = Decimal(str(round(learned.x, 6)))
            pose.visual_y = Decimal(str(round(learned.y, 6)))
            pose.visual_heading_deg = Decimal(str(round(learned.heading_deg, 3)))
            pose.relative_z_m = Decimal(str(round(learned.z, 3)))
            pose.confidence = Decimal("0.85000")
            pose.algorithm = algorithm
            # Preserve the existing plan-review state. This operation replaces
            # only the relative 3-D camera track and never changes x/y plan
            # coordinates or claims a new plan alignment.
            keyframe.is_warp_point = keyframe.frame_index in selected_station_indices
            warp_count += int(keyframe.is_warp_point)
        if apply:
            capture = db.get(Capture, capture_id)
            if capture is None:
                raise RuntimeError(f"Missing Capture {capture_id}")
            object_key = (
                f"projects/{capture.project_id}/captures/{capture.id}/"
                "localization/spatial-model.json"
            )
            upload_file(
                key=object_key,
                source=str(spatial_model_path),
                content_type="application/json",
            )
            media = db.scalar(
                select(MediaFile).where(MediaFile.object_key == object_key)
            )
            if media is None:
                db.add(
                    MediaFile(
                        project_id=capture.project_id,
                        media_kind="SFM_SPATIAL_MODEL",
                        bucket=get_settings().s3_bucket,
                        object_key=object_key,
                        original_filename="spatial-model.json",
                        content_type="application/json",
                        size_bytes=spatial_model_path.stat().st_size,
                        upload_status="READY",
                    )
                )
            else:
                media.size_bytes = spatial_model_path.stat().st_size
                media.upload_status = "READY"
            db.commit()
        else:
            db.rollback()
    return len(rows), warp_count, backup_path


def restore_trial(backup_path: Path, *, apply: bool) -> int:
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    restored = 0
    with SessionLocal() as db:
        for row in backup["rows"]:
            keyframe = db.get(Keyframe, uuid.UUID(row["keyframe_id"]))
            if keyframe is None:
                raise RuntimeError(f"Missing Keyframe {row['keyframe_id']}")
            pose = db.scalar(
                select(CameraPose).where(CameraPose.keyframe_id == keyframe.id)
            )
            if pose is None:
                raise RuntimeError(f"Missing CameraPose for {row['keyframe_id']}")
            keyframe.is_warp_point = bool(row["is_warp_point"])
            pose.visual_x = (
                Decimal(row["visual_x"]) if row["visual_x"] is not None else None
            )
            pose.visual_y = (
                Decimal(row["visual_y"]) if row["visual_y"] is not None else None
            )
            pose.visual_heading_deg = (
                Decimal(row["visual_heading_deg"])
                if row["visual_heading_deg"] is not None
                else None
            )
            pose.relative_z_m = (
                Decimal(row["relative_z_m"])
                if row["relative_z_m"] is not None
                else None
            )
            pose.confidence = Decimal(row["confidence"])
            pose.algorithm = row["algorithm"]
            pose.needs_review = bool(row["needs_review"])
            restored += 1
        if apply:
            db.commit()
        else:
            db.rollback()
    return restored


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_id", type=uuid.UUID)
    parser.add_argument("model_path", type=Path, nargs="?")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("outputs/rig-pose-trial-backups"),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--algorithm", default=DEFAULT_ALGORITHM)
    parser.add_argument("--restore-from", type=Path)
    args = parser.parse_args()
    if args.restore_from is not None:
        restored = restore_trial(args.restore_from, apply=args.apply)
        mode = "restored" if args.apply else "previewed restore of"
        print(f"{mode} rows={restored} backup={args.restore_from}")
        return
    if args.model_path is None:
        parser.error("model_path is required unless --restore-from is used")
    rows, warps, backup = apply_trial(
        args.capture_id,
        args.model_path,
        args.backup_dir,
        apply=args.apply,
        algorithm=args.algorithm,
    )
    mode = "applied" if args.apply else "previewed"
    print(f"{mode} rows={rows} warp_points={warps} backup={backup}")


if __name__ == "__main__":
    main()
