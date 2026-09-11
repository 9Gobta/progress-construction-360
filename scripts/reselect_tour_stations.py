"""Rebuild Virtual Tour stations for existing localized captures."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from progress_api.db import SessionLocal
from progress_api.models import CameraPose, Capture, Keyframe
from progress_api.services.video_pipeline import (
    TourStationSample,
    remove_consecutive_duplicate_warp_points,
    select_spatial_warp_points,
)
from sqlalchemy import distinct, select

PROTECTED_REFERENCE_CAPTURE_ID = uuid.UUID("b78c9804-76c2-4e96-93d4-53cf55ffba3f")


def reselect(
    capture_id: uuid.UUID,
    *,
    apply: bool,
    backup_root: Path,
    exact_duplicates_only: bool,
    restore_root: Path | None,
) -> tuple[int, int, bool]:
    with SessionLocal() as db:
        rows = db.execute(
            select(Keyframe, CameraPose)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .where(Keyframe.capture_id == capture_id)
            .order_by(Keyframe.frame_index)
        ).all()
        if not rows:
            raise RuntimeError(f"Localized keyframes not found: {capture_id}")
        old_count = sum(keyframe.is_warp_point for keyframe, _pose in rows)
        if capture_id == PROTECTED_REFERENCE_CAPTURE_ID:
            return old_count, old_count, True
        restored_ids: set[uuid.UUID] | None = None
        if restore_root is not None:
            restore_path = restore_root / f"{capture_id}.json"
            if not restore_path.is_file():
                raise RuntimeError(f"Station backup not found: {restore_path}")
            restore_payload = json.loads(restore_path.read_text(encoding="utf-8"))
            restored_ids = {
                uuid.UUID(value) for value in restore_payload["warp_keyframe_ids"]
            }
        candidates = [
            (keyframe, pose)
            for keyframe, pose in rows
            if (
                keyframe.id in restored_ids
                if restored_ids is not None
                else keyframe.is_warp_point
            )
        ]
        if exact_duplicates_only:
            candidate_indices = {keyframe.frame_index for keyframe, _pose in candidates}
            candidate_samples = [
                TourStationSample(
                    frame_index=keyframe.frame_index,
                    timestamp_ms=keyframe.timestamp_ms,
                    quality_status=keyframe.quality_status,
                    x=float(pose.visual_x if pose.visual_x is not None else pose.x),
                    y=float(pose.visual_y if pose.visual_y is not None else pose.y),
                    heading_deg=float(
                        pose.visual_heading_deg
                        if pose.visual_heading_deg is not None
                        else pose.heading_deg
                    ),
                )
                for keyframe, pose in rows
            ]
            selected_indices = remove_consecutive_duplicate_warp_points(
                candidate_samples,
                candidate_indices,
            )
            selected_ids = {
                keyframe.id
                for keyframe, _pose in rows
                if keyframe.frame_index in selected_indices
            }
        else:
            samples = [
                TourStationSample(
                    frame_index=keyframe.frame_index,
                    timestamp_ms=keyframe.timestamp_ms,
                    quality_status=keyframe.quality_status,
                    x=float(pose.visual_x if pose.visual_x is not None else pose.x),
                    y=float(pose.visual_y if pose.visual_y is not None else pose.y),
                    heading_deg=float(
                        pose.visual_heading_deg
                        if pose.visual_heading_deg is not None
                        else pose.heading_deg
                    ),
                )
                for keyframe, pose in rows
            ]
            selected_indices = select_spatial_warp_points(samples)
            selected_ids = {
                keyframe.id
                for keyframe, _pose in rows
                if keyframe.frame_index in selected_indices
            }
        if apply:
            backup_root.mkdir(parents=True, exist_ok=True)
            (backup_root / f"{capture_id}.json").write_text(
                json.dumps(
                    {
                        "capture_id": str(capture_id),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "warp_keyframe_ids": [
                            str(keyframe.id)
                            for keyframe, _pose in rows
                            if keyframe.is_warp_point
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            for keyframe, _pose in rows:
                keyframe.is_warp_point = keyframe.id in selected_ids
            db.commit()
        return old_count, len(selected_ids), False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_ids", nargs="*", type=uuid.UUID)
    parser.add_argument(
        "--all-localized",
        action="store_true",
        help="update every capture that has at least one Camera Pose",
    )
    parser.add_argument("--project-id", type=uuid.UUID)
    parser.add_argument(
        "--confirmed-through",
        type=date.fromisoformat,
        help="select non-default-start captures in the project through YYYY-MM-DD",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--exact-duplicates-only",
        action="store_true",
        help="keep the existing cadence and remove only consecutive identical positions",
    )
    parser.add_argument(
        "--restore-root",
        type=Path,
        help="use station IDs from an earlier backup as the selection baseline",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path(".codex_tmp/tour-station-backups"),
    )
    args = parser.parse_args()
    capture_ids = list(args.capture_ids)
    if args.all_localized:
        with SessionLocal() as db:
            capture_ids = list(db.scalars(
                select(distinct(Keyframe.capture_id))
                .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
                .order_by(Keyframe.capture_id)
            ))
    if args.confirmed_through:
        if not args.project_id:
            parser.error("--confirmed-through requires --project-id")
        cutoff = datetime.combine(args.confirmed_through, time.min) + timedelta(days=1)
        with SessionLocal() as db:
            capture_ids = list(db.scalars(
                select(distinct(Capture.id))
                .join(Keyframe, Keyframe.capture_id == Capture.id)
                .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
                .where(
                    Capture.project_id == args.project_id,
                    Capture.captured_at < cutoff,
                    ~(
                        (Capture.start_x == 0.5)
                        & (Capture.start_y == 0.5)
                    ),
                )
                .order_by(Capture.captured_at)
            ))
    if not capture_ids:
        parser.error("provide capture_ids or --all-localized")
    total_old = 0
    total_new = 0
    skipped = 0
    for capture_id in capture_ids:
        old_count, new_count, protected = reselect(
            capture_id,
            apply=args.apply,
            backup_root=args.backup_root,
            exact_duplicates_only=args.exact_duplicates_only,
            restore_root=args.restore_root,
        )
        total_old += old_count
        total_new += new_count
        if protected:
            skipped += 1
            action = "protected-reference-skipped"
        else:
            action = "updated" if args.apply else "preview"
        print(f"{capture_id}: {action} {old_count} -> {new_count} stations")
    print(
        f"captures={len(capture_ids)} total_stations={total_old}->{total_new} "
        f"protected_skipped={skipped} mode={'apply' if args.apply else 'preview'}"
    )


if __name__ == "__main__":
    main()
