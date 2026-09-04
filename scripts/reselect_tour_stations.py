"""Rebuild Virtual Tour stations for existing localized captures."""

from __future__ import annotations

import argparse
import uuid
from datetime import date, datetime, time, timedelta

from progress_api.db import SessionLocal
from progress_api.models import CameraPose, Capture, Keyframe
from progress_api.services.video_pipeline import (
    TourStationSample,
    select_spatial_warp_points,
)
from sqlalchemy import distinct, select


def reselect(capture_id: uuid.UUID, *, apply: bool) -> tuple[int, int]:
    with SessionLocal() as db:
        rows = db.execute(
            select(Keyframe, CameraPose)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .where(Keyframe.capture_id == capture_id)
            .order_by(Keyframe.frame_index)
        ).all()
        if not rows:
            raise RuntimeError(f"Localized keyframes not found: {capture_id}")
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
        selected = select_spatial_warp_points(samples)
        old_count = sum(keyframe.is_warp_point for keyframe, _pose in rows)
        if apply:
            for keyframe, _pose in rows:
                keyframe.is_warp_point = keyframe.frame_index in selected
            db.commit()
        return old_count, len(selected)


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
    for capture_id in capture_ids:
        old_count, new_count = reselect(capture_id, apply=args.apply)
        total_old += old_count
        total_new += new_count
        action = "updated" if args.apply else "preview"
        print(f"{capture_id}: {action} {old_count} -> {new_count} stations")
    print(
        f"captures={len(capture_ids)} total_stations={total_old}->{total_new} "
        f"mode={'apply' if args.apply else 'preview'}"
    )


if __name__ == "__main__":
    main()
