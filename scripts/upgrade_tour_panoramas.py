"""Upgrade selected legacy Capture stations to 4K panoramas in-place.

The source video, keyframe IDs, camera poses and progress evidence are left
unchanged.  Run one Capture at a time on a workstation because decoding 8K
HEVC is intentionally CPU intensive.
"""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path, PurePath

from progress_api.db import SessionLocal
from progress_api.models import Capture, Keyframe, MediaFile
from progress_api.object_storage import download_media_file, upload_file
from progress_api.services.insta360_stitching import stitch_insv
from progress_api.services.temporary_workspace import temporary_workspace
from progress_api.services.video_pipeline import (
    PROXY_WIDTH,
    _extract_tour_panoramas,
    _fps,
    _probe,
)
from sqlalchemy import select


def upgrade(capture_id: uuid.UUID) -> tuple[int, int]:
    with SessionLocal() as db:
        capture = db.get(Capture, capture_id)
        if capture is None:
            raise RuntimeError(f"Capture not found: {capture_id}")
        source_media = db.get(MediaFile, capture.source_video_id)
        if source_media is None or source_media.upload_status != "READY":
            raise RuntimeError(f"Source video is not ready: {capture_id}")
        rows = db.execute(
            select(Keyframe, MediaFile)
            .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
            .where(
                Keyframe.capture_id == capture_id,
                Keyframe.is_warp_point.is_(True),
                Keyframe.quality_status == "USABLE",
            )
            .order_by(Keyframe.frame_index)
        ).all()
        pending = [
            (keyframe, media)
            for keyframe, media in rows
            if not (media.original_filename or "").startswith("tour-4k-")
        ]
        if not pending:
            return 0, len(rows)

        suffix = PurePath(
            source_media.original_filename or source_media.object_key
        ).suffix.lower()
        with temporary_workspace(prefix="upgrade-tour-") as temporary:
            workdir = Path(temporary)
            source = workdir / f"source{suffix}"
            download_media_file(
                bucket=source_media.bucket,
                key=source_media.object_key,
                destination=str(source),
            )
            processing_source = source
            if suffix == ".insv":
                processing_source = workdir / "stitched.mp4"
                stitch_insv(source=source, destination=processing_source)
            _payload, stream = _probe(processing_source)
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            if width <= PROXY_WIDTH:
                return 0, len(rows)
            images = _extract_tour_panoramas(
                source=processing_source,
                destination_dir=workdir / "tour-panoramas",
                frame_indices=[keyframe.frame_index for keyframe, _media in pending],
                source_fps=float(_fps(stream.get("avg_frame_rate", "0/1"))),
                width=width,
                height=height,
            )
            for keyframe, media in pending:
                image = images[keyframe.frame_index]
                upload_file(
                    key=media.object_key,
                    source=str(image),
                    content_type="image/jpeg",
                )
                media.original_filename = f"tour-4k-{keyframe.frame_index:06d}.jpg"
                media.content_type = "image/jpeg"
                media.size_bytes = image.stat().st_size
                media.upload_status = "READY"
            db.commit()
        return len(pending), len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_ids", nargs="+", type=uuid.UUID)
    args = parser.parse_args()
    for capture_id in args.capture_ids:
        upgraded, total = upgrade(capture_id)
        print(f"{capture_id}: upgraded {upgraded}/{total} tour panoramas")


if __name__ == "__main__":
    main()
