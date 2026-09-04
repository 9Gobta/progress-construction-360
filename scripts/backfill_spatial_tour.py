"""Build a real SfM point cloud and matching tour camera track for a capture."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from progress_api.db import SessionLocal
from progress_api.models import CameraPose, Capture, Keyframe, MediaFile
from progress_api.object_storage import download_media_file
from progress_api.services.localization import _save_spatial_model
from progress_api.services.sfm_localization import recover_sfm_path
from progress_api.services.temporary_workspace import temporary_workspace
from progress_api.services.video_pipeline import (
    TourStationSample,
    build_spatial_visibility_targets,
    select_spatial_warp_points,
)


PROTECTED_REFERENCE_CAPTURE_ID = uuid.UUID("b78c9804-76c2-4e96-93d4-53cf55ffba3f")


def backfill(capture_id: uuid.UUID, *, apply: bool, backup_root: Path) -> dict[str, object]:
    if capture_id == PROTECTED_REFERENCE_CAPTURE_ID:
        raise RuntimeError("The approved 20/12/2568 reference capture is protected")
    with SessionLocal() as db:
        capture = db.get(Capture, capture_id)
        if capture is None:
            raise RuntimeError(f"Capture not found: {capture_id}")
        source_media = db.get(MediaFile, capture.source_video_id)
        if source_media is None:
            raise RuntimeError(f"Source video not found: {capture_id}")
        rows = list(db.execute(
            select(Keyframe, CameraPose)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .where(Keyframe.capture_id == capture_id)
            .order_by(Keyframe.timestamp_ms)
        ).all())
        if not rows:
            raise RuntimeError(f"Camera poses not found: {capture_id}")
        end_timestamp_ms = rows[-1][0].timestamp_ms
        backup = {
            "capture_id": str(capture_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "poses": [
                {
                    "keyframe_id": str(keyframe.id),
                    "is_warp_point": keyframe.is_warp_point,
                    "visual_x": str(pose.visual_x) if pose.visual_x is not None else None,
                    "visual_y": str(pose.visual_y) if pose.visual_y is not None else None,
                    "visual_heading_deg": str(pose.visual_heading_deg) if pose.visual_heading_deg is not None else None,
                    "visual_z": str(pose.visual_z) if pose.visual_z is not None else None,
                    "visual_ground_z": str(pose.visual_ground_z) if pose.visual_ground_z is not None else None,
                    "orientation_q": [
                        str(getattr(pose, f"orientation_q{axis}"))
                        if getattr(pose, f"orientation_q{axis}") is not None else None
                        for axis in "xyzw"
                    ],
                    "relative_z_m": str(pose.relative_z_m) if pose.relative_z_m is not None else None,
                    "algorithm": pose.algorithm,
                }
                for keyframe, pose in rows
            ],
        }

        print(f"{capture_id}: downloading source video", flush=True)
        with temporary_workspace(prefix=f"spatial-{str(capture_id)[:8]}-") as temporary:
            workspace = Path(temporary)
            source = workspace / "source.mp4"
            model_path = workspace / "spatial-model.json"
            download_media_file(
                bucket=source_media.bucket,
                key=source_media.object_key,
                destination=str(source),
            )
            print(f"{capture_id}: reconstructing SfM point cloud", flush=True)
            samples = recover_sfm_path(
                source,
                end_timestamp_ms=end_timestamp_ms,
                spatial_model_output=model_path,
            )
            by_timestamp = {sample.timestamp_ms: sample for sample in samples}
            if any(keyframe.timestamp_ms not in by_timestamp for keyframe, _pose in rows):
                raise RuntimeError(f"SfM track does not cover every keyframe: {capture_id}")
            station_samples = []
            for keyframe, pose in rows:
                sample = by_timestamp[keyframe.timestamp_ms]
                station_samples.append(TourStationSample(
                    frame_index=keyframe.frame_index,
                    timestamp_ms=keyframe.timestamp_ms,
                    quality_status=keyframe.quality_status,
                    x=sample.x,
                    y=sample.y,
                    heading_deg=sample.heading_deg,
                ))
            selected = select_spatial_warp_points(station_samples)
            visibility = build_spatial_visibility_targets(station_samples, selected)
            keyframe_by_index = {
                keyframe.frame_index: keyframe for keyframe, _pose in rows
            }
            model = json.loads(model_path.read_text(encoding="utf-8"))
            if apply:
                backup_root.mkdir(parents=True, exist_ok=True)
                backup_path = backup_root / f"{capture_id}.json"
                backup_path.write_text(json.dumps(backup, indent=2), encoding="utf-8")
                for keyframe, pose in rows:
                    sample = by_timestamp[keyframe.timestamp_ms]
                    pose.visual_x = Decimal(str(round(sample.x, 6)))
                    pose.visual_y = Decimal(str(round(sample.y, 6)))
                    pose.visual_heading_deg = Decimal(str(round(sample.heading_deg, 3)))
                    pose.relative_z_m = Decimal(str(round(sample.relative_z, 3)))
                    pose.visual_z = Decimal(str(round(sample.relative_z, 6)))
                    pose.visual_ground_z = Decimal(str(round(sample.relative_z - 1.65, 6)))
                    if sample.orientation_q is None:
                        raise RuntimeError(f"SfM orientation is missing: {capture_id}")
                    for axis, value in zip("xyzw", sample.orientation_q, strict=True):
                        setattr(
                            pose,
                            f"orientation_q{axis}",
                            Decimal(str(round(value, 12))),
                        )
                    if "+pycolmap-spatial-v1" not in pose.algorithm:
                        pose.algorithm = f"{pose.algorithm}+pycolmap-spatial-v1"
                    keyframe.is_warp_point = keyframe.frame_index in selected
                    pose.visibility_target_ids = (
                        json.dumps(
                            [
                                str(keyframe_by_index[index].id)
                                for index in visibility[keyframe.frame_index]
                            ],
                            separators=(",", ":"),
                        )
                        if keyframe.is_warp_point
                        else None
                    )
                _save_spatial_model(db, capture=capture, model_path=model_path)
                db.commit()
            return {
                "capture_id": str(capture_id),
                "point_count": int(model.get("point_count", 0)),
                "keyframes": len(rows),
                "stations": len(selected),
                "applied": apply,
            }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_ids", nargs="+", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-root", type=Path, default=Path(".codex_tmp/spatial-tour-backups"))
    parser.add_argument("--status-path", type=Path)
    args = parser.parse_args()
    results: list[dict[str, object]] = []

    def save_status(*, current: uuid.UUID | None = None) -> None:
        if not args.status_path:
            return
        args.status_path.parent.mkdir(parents=True, exist_ok=True)
        args.status_path.write_text(json.dumps({
            "total": len(args.capture_ids),
            "completed": len(results),
            "current_capture_id": str(current) if current else None,
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    save_status()
    for capture_id in args.capture_ids:
        save_status(current=capture_id)
        try:
            result = backfill(capture_id, apply=args.apply, backup_root=args.backup_root)
        except Exception as exc:
            result = {
                "capture_id": str(capture_id),
                "applied": False,
                "error": str(exc),
            }
        results.append(result)
        save_status()
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
