"""Create dense portal visibility for captures with a real SfM trajectory."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path

from progress_api.db import SessionLocal
from progress_api.models import CameraPose, Capture, Keyframe
from progress_api.services.video_pipeline import (
    TourStationSample,
    build_spatial_visibility_targets,
)
from sqlalchemy import select

PROTECTED_REFERENCE_CAPTURE_ID = uuid.UUID("b78c9804-76c2-4e96-93d4-53cf55ffba3f")


def apply_capture(capture_id: uuid.UUID, *, apply: bool, backup_root: Path) -> dict[str, object]:
    if capture_id == PROTECTED_REFERENCE_CAPTURE_ID:
        return {"capture_id": str(capture_id), "skipped": "protected-reference"}
    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(Keyframe, CameraPose)
                .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
                .where(Keyframe.capture_id == capture_id)
                .order_by(Keyframe.timestamp_ms)
            ).all()
        )
        if not rows:
            return {"capture_id": str(capture_id), "skipped": "no-camera-poses"}

        samples = [
            TourStationSample(
                frame_index=keyframe.frame_index,
                timestamp_ms=keyframe.timestamp_ms,
                quality_status=keyframe.quality_status,
                x=float(pose.visual_x) if pose.visual_x is not None else None,
                y=float(pose.visual_y) if pose.visual_y is not None else None,
                heading_deg=(
                    float(pose.visual_heading_deg)
                    if pose.visual_heading_deg is not None
                    else None
                ),
            )
            for keyframe, pose in rows
        ]
        selected = {keyframe.frame_index for keyframe, _pose in rows if keyframe.is_warp_point}
        graph = build_spatial_visibility_targets(samples, selected)
        keyframe_by_index = {keyframe.frame_index: keyframe for keyframe, _pose in rows}
        expected = {
            keyframe_by_index[source].id: [keyframe_by_index[target].id for target in targets]
            for source, targets in graph.items()
        }
        current = {
            keyframe.id: [uuid.UUID(value) for value in json.loads(pose.visibility_target_ids)]
            for keyframe, pose in rows
            if pose.visibility_target_ids is not None
        }
        if current == expected:
            return {
                "capture_id": str(capture_id),
                "stations": len(graph),
                "skipped": "already-current",
            }
        backup = {
            "capture_id": str(capture_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "visibility": {
                str(keyframe.id): pose.visibility_target_ids
                for keyframe, pose in rows
                if pose.visibility_target_ids is not None
            },
        }
        if apply:
            backup_root.mkdir(parents=True, exist_ok=True)
            (backup_root / f"{capture_id}.json").write_text(
                json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            for keyframe, pose in rows:
                pose.visibility_target_ids = (
                    json.dumps(
                        [
                            str(keyframe_by_index[index].id)
                            for index in graph[keyframe.frame_index]
                        ],
                        separators=(",", ":"),
                    )
                    if keyframe.frame_index in graph
                    else None
                )
            db.commit()
        return {
            "capture_id": str(capture_id),
            "stations": len(graph),
            "minimum_visible": min((len(targets) for targets in graph.values()), default=0),
            "maximum_visible": max((len(targets) for targets in graph.values()), default=0),
            "applied": apply,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_ids", nargs="*", type=uuid.UUID)
    parser.add_argument("--project-id", type=uuid.UUID)
    parser.add_argument("--confirmed-from")
    parser.add_argument("--confirmed-through")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path(".codex_tmp/spatial-visibility-backups"),
    )
    args = parser.parse_args()
    capture_ids = list(args.capture_ids)
    if args.project_id and args.confirmed_through:
        cutoff_date = date.fromisoformat(args.confirmed_through)
        cutoff = datetime.combine(cutoff_date, time.max, tzinfo=timezone.utc)
        start = (
            datetime.combine(
                date.fromisoformat(args.confirmed_from),
                time.min,
                tzinfo=timezone.utc,
            )
            if args.confirmed_from
            else datetime.min.replace(tzinfo=timezone.utc)
        )
        with SessionLocal() as db:
            capture_ids.extend(
                db.scalars(
                    select(Capture.id)
                    .where(
                        Capture.project_id == args.project_id,
                        Capture.captured_at >= start,
                        Capture.captured_at <= cutoff,
                    )
                    .order_by(Capture.captured_at)
                ).all()
            )
    if not capture_ids:
        raise SystemExit("Provide capture IDs or --project-id with --confirmed-through")
    for capture_id in dict.fromkeys(capture_ids):
        print(json.dumps(apply_capture(capture_id, apply=args.apply, backup_root=args.backup_root)))


if __name__ == "__main__":
    main()
