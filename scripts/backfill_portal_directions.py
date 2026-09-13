"""Verify adjacent portal bearings directly from their panorama image pairs."""

from __future__ import annotations

import argparse
import json
import uuid
from itertools import pairwise
from pathlib import Path

from progress_api.db import SessionLocal
from progress_api.models import CameraPose, Capture, Keyframe, MediaFile
from progress_api.object_storage import download_media_file
from progress_api.services.portal_verification import estimate_portal_direction
from progress_api.services.temporary_workspace import temporary_workspace
from sqlalchemy import select

PROTECTED_REFERENCE_CAPTURE_ID = uuid.UUID("b78c9804-76c2-4e96-93d4-53cf55ffba3f")


def backfill(capture_id: uuid.UUID, *, apply: bool) -> dict[str, object]:
    if capture_id == PROTECTED_REFERENCE_CAPTURE_ID:
        raise RuntimeError("The approved 20/12/2568 reference capture is protected")
    with SessionLocal() as db:
        if db.get(Capture, capture_id) is None:
            raise RuntimeError(f"Capture not found: {capture_id}")
        rows = list(
            db.execute(
                select(Keyframe, CameraPose, MediaFile)
                .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
                .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
                .where(Keyframe.capture_id == capture_id, Keyframe.is_warp_point.is_(True))
                .order_by(Keyframe.timestamp_ms)
            ).all()
        )
        if len(rows) < 2:
            raise RuntimeError("Capture has fewer than two localized tour stations")
        verified_count = 0
        failed_pairs: list[list[int]] = []
        with temporary_workspace(prefix=f"portal-{str(capture_id)[:8]}-") as temporary:
            workspace = Path(temporary)
            local_images: dict[uuid.UUID, Path] = {}
            for keyframe, _pose, media in rows:
                destination = workspace / f"{keyframe.frame_index:06d}.jpg"
                download_media_file(
                    bucket=media.bucket,
                    key=media.object_key,
                    destination=str(destination),
                )
                local_images[keyframe.id] = destination
            directions: dict[uuid.UUID, dict[str, dict[str, float | int | str]]] = {}
            for (source, _source_pose, _source_media), (
                target,
                _target_pose,
                _target_media,
            ) in pairwise(rows):
                verified = estimate_portal_direction(
                    local_images[source.id], local_images[target.id]
                )
                if verified is None:
                    failed_pairs.append([source.timestamp_ms, target.timestamp_ms])
                    continue
                common = {
                    "confidence": round(verified.confidence, 5),
                    "inliers": verified.inliers,
                    "dispersion_deg": round(verified.dispersion_deg, 3),
                    "method": "panorama-pair-essential-matrix-v1",
                }
                directions.setdefault(source.id, {})[str(target.id)] = {
                    **common,
                    "local_yaw_deg": round(verified.forward_yaw_deg, 3),
                }
                directions.setdefault(target.id, {})[str(source.id)] = {
                    **common,
                    "local_yaw_deg": round(verified.backward_yaw_deg, 3),
                }
                verified_count += 1
            if apply:
                for _keyframe, pose, _media in rows:
                    pose.portal_directions_json = json.dumps(
                        directions.get(pose.keyframe_id, {}), separators=(",", ":")
                    )
                db.commit()
        return {
            "capture_id": str(capture_id),
            "station_count": len(rows),
            "pair_count": len(rows) - 1,
            "verified_pair_count": verified_count,
            "failed_pairs": failed_pairs,
            "applied": apply,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_id", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(backfill(args.capture_id, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
