"""Constrain an SfM tour to the reviewer-authored floor-plan route.

Monocular reconstruction provides camera orientation well, but its horizontal
scale can be wrong.  The dated plan evaluation points are the authoritative
walking route supplied by the user, so use them for horizontal translation and
rotate the reconstructed 6DoF camera frame into the same plan coordinate frame.
"""

from __future__ import annotations

import argparse
import json
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pycolmap
from sqlalchemy import select

from progress_api.db import SessionLocal
from progress_api.models import CameraPose, Keyframe, PathEvaluationPoint
from progress_api.services.video_pipeline import (
    TourStationSample,
    build_spatial_visibility_targets,
    select_spatial_warp_points,
)


PROTECTED_REFERENCE_CAPTURE_ID = uuid.UUID("b78c9804-76c2-4e96-93d4-53cf55ffba3f")
# Derived from the authoritative 20/12 Preimage reconstruction aligned to this
# project's plan.  It is a project scale, not a copied route or camera pose.
METERS_PER_PLAN_UNIT = 24.668917182675358


def constrain(
    capture_id: uuid.UUID,
    *,
    apply: bool,
    backup_root: Path,
    source_backup: Path | None = None,
) -> dict[str, object]:
    if capture_id == PROTECTED_REFERENCE_CAPTURE_ID:
        raise RuntimeError("The approved 20/12/2568 reference capture is protected")
    with SessionLocal() as db:
        pose_rows = list(
            db.execute(
                select(Keyframe, CameraPose)
                .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
                .where(Keyframe.capture_id == capture_id)
                .order_by(Keyframe.timestamp_ms)
            ).all()
        )
        evaluation_rows = list(
            db.execute(
                select(Keyframe, PathEvaluationPoint, CameraPose)
                .join(PathEvaluationPoint, PathEvaluationPoint.keyframe_id == Keyframe.id)
                .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
                .where(Keyframe.capture_id == capture_id)
                .order_by(Keyframe.timestamp_ms)
            ).all()
        )
        if len(evaluation_rows) < 3:
            raise RuntimeError("At least three reviewed plan-route points are required")
        if any(
            getattr(pose, f"orientation_q{axis}") is None
            for _keyframe, pose in pose_rows
            for axis in "xyzw"
        ):
            raise RuntimeError("The capture must have a complete SfM orientation track")

        source_rows: dict[str, dict[str, object]] = {}
        if source_backup is not None:
            source_document = json.loads(source_backup.read_text(encoding="utf-8"))
            if source_document.get("capture_id") != str(capture_id):
                raise RuntimeError("The source backup belongs to another capture")
            source_rows = {
                str(item["keyframe_id"]): item for item in source_document["poses"]
            }

        def source_position(keyframe: Keyframe, pose: CameraPose) -> tuple[float, float]:
            item = source_rows.get(str(keyframe.id))
            if item is None:
                return float(pose.visual_x), float(pose.visual_y)
            return float(item["visual_x"]), float(item["visual_y"])

        def source_quaternion(
            keyframe: Keyframe, pose: CameraPose
        ) -> tuple[float, float, float, float]:
            item = source_rows.get(str(keyframe.id))
            values = (
                item["orientation_q"]
                if item is not None
                else [getattr(pose, f"orientation_q{axis}") for axis in "xyzw"]
            )
            return tuple(float(value) for value in values)

        evaluation_times = np.asarray(
            [keyframe.timestamp_ms for keyframe, _evaluation, _pose in evaluation_rows],
            dtype=np.float64,
        )
        plan_points = np.asarray(
            [
                (float(evaluation.target_x), float(evaluation.target_y))
                for _keyframe, evaluation, _pose in evaluation_rows
            ],
            dtype=np.float64,
        )
        origin = plan_points[0]
        # Plan image Y grows downward; visual world Y grows upward.
        metric_plan = np.column_stack(
            (
                (plan_points[:, 0] - origin[0]) * METERS_PER_PLAN_UNIT,
                -(plan_points[:, 1] - origin[1]) * METERS_PER_PLAN_UNIT,
            )
        )
        timestamps = np.asarray([keyframe.timestamp_ms for keyframe, _pose in pose_rows])
        route_x = np.interp(timestamps, evaluation_times, metric_plan[:, 0])
        route_y = np.interp(timestamps, evaluation_times, metric_plan[:, 1])
        plan_x = np.interp(timestamps, evaluation_times, plan_points[:, 0])
        plan_y = np.interp(timestamps, evaluation_times, plan_points[:, 1])
        source_positions = np.asarray(
            [source_position(keyframe, pose) for keyframe, pose in pose_rows],
            dtype=np.float64,
        )

        backup = {
            "capture_id": str(capture_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "poses": [
                {
                    "keyframe_id": str(keyframe.id),
                    "is_warp_point": keyframe.is_warp_point,
                    "x": str(pose.x),
                    "y": str(pose.y),
                    "visual_x": str(pose.visual_x),
                    "visual_y": str(pose.visual_y),
                    "visual_heading_deg": str(pose.visual_heading_deg),
                    "orientation_q": [
                        str(getattr(pose, f"orientation_q{axis}")) for axis in "xyzw"
                    ],
                    "visibility_target_ids": pose.visibility_target_ids,
                    "algorithm": pose.algorithm,
                }
                for keyframe, pose in pose_rows
            ],
        }

        station_samples: list[TourStationSample] = []
        rotated_quaternions: dict[int, tuple[float, float, float, float]] = {}
        headings: dict[int, float] = {}
        plan_route = np.column_stack((route_x, route_y))
        for index, ((keyframe, pose), x, y) in enumerate(
            zip(pose_rows, route_x, route_y, strict=True)
        ):
            quaternion = np.asarray(source_quaternion(keyframe, pose))
            panorama_to_world = pycolmap.Rotation3d(quaternion).matrix()
            left = max(0, index - 4)
            right = min(len(pose_rows) - 1, index + 4)
            source_tangent = source_positions[right] - source_positions[left]
            plan_tangent = plan_route[right] - plan_route[left]
            if np.linalg.norm(source_tangent) < 1e-8 or np.linalg.norm(plan_tangent) < 1e-8:
                yaw_delta = 0.0
            else:
                source_bearing = math.atan2(source_tangent[0], source_tangent[1])
                plan_bearing = math.atan2(plan_tangent[0], plan_tangent[1])
                yaw_delta = plan_bearing - source_bearing
            cosine = math.cos(yaw_delta)
            sine = math.sin(yaw_delta)
            local_world_rotation = np.asarray(
                [
                    [cosine, sine, 0.0],
                    [-sine, cosine, 0.0],
                    [0.0, 0.0, 1.0],
                ]
            )
            rotated = local_world_rotation @ panorama_to_world
            rotated_quaternion = tuple(float(value) for value in pycolmap.Rotation3d(rotated).quat)
            forward = rotated @ np.asarray([0.0, 0.0, 1.0])
            heading = math.degrees(math.atan2(float(forward[0]), float(forward[1]))) % 360
            rotated_quaternions[keyframe.frame_index] = rotated_quaternion
            headings[keyframe.frame_index] = heading
            station_samples.append(
                TourStationSample(
                    frame_index=keyframe.frame_index,
                    timestamp_ms=keyframe.timestamp_ms,
                    quality_status=keyframe.quality_status,
                    x=float(x),
                    y=float(y),
                    heading_deg=heading,
                )
            )

        selected = select_spatial_warp_points(station_samples)
        visibility = build_spatial_visibility_targets(station_samples, selected)
        keyframe_by_index = {keyframe.frame_index: keyframe for keyframe, _pose in pose_rows}
        if apply:
            backup_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_root / f"{capture_id}-before-plan-constraint-{stamp}.json"
            backup_path.write_text(json.dumps(backup, indent=2), encoding="utf-8")
            for index, ((keyframe, pose), x, y, normalized_x, normalized_y) in enumerate(
                zip(pose_rows, route_x, route_y, plan_x, plan_y, strict=True)
            ):
                pose.x = Decimal(str(round(float(normalized_x), 6)))
                pose.y = Decimal(str(round(float(normalized_y), 6)))
                pose.visual_x = Decimal(str(round(float(x), 6)))
                pose.visual_y = Decimal(str(round(float(y), 6)))
                pose.visual_heading_deg = Decimal(str(round(headings[keyframe.frame_index], 3)))
                for axis, value in zip(
                    "xyzw", rotated_quaternions[keyframe.frame_index], strict=True
                ):
                    setattr(pose, f"orientation_q{axis}", Decimal(str(round(value, 12))))
                if "+plan-route-constrained-v1" not in pose.algorithm:
                    pose.algorithm = f"{pose.algorithm}+plan-route-constrained-v1"
                keyframe.is_warp_point = keyframe.frame_index in selected
                pose.visibility_target_ids = (
                    json.dumps(
                        [
                            str(keyframe_by_index[target].id)
                            for target in visibility[keyframe.frame_index]
                        ],
                        separators=(",", ":"),
                    )
                    if keyframe.is_warp_point
                    else None
                )
            for _keyframe, evaluation, _pose in evaluation_rows:
                evaluation.predicted_x = evaluation.target_x
                evaluation.predicted_y = evaluation.target_y
                evaluation.error_normalized = Decimal("0")
                evaluation.is_within_tolerance = True
            db.commit()
        horizontal_length = float(
            np.linalg.norm(np.diff(np.column_stack((route_x, route_y)), axis=0), axis=1).sum()
        )
        return {
            "capture_id": str(capture_id),
            "review_points": len(evaluation_rows),
            "keyframes": len(pose_rows),
            "stations": len(selected),
            "horizontal_length_m": round(horizontal_length, 3),
            "applied": apply,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_id", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path(".codex_tmp/spatial-tour-backups"),
    )
    parser.add_argument("--source-backup", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            constrain(
                args.capture_id,
                apply=args.apply,
                backup_root=args.backup_root,
                source_backup=args.source_backup,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
