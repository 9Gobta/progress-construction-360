from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from progress_api.db import SessionLocal
from progress_api.models.capture import Keyframe, MediaFile
from progress_api.object_storage import download_media_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_id", type=uuid.UUID)
    parser.add_argument("output", type=Path)
    parser.add_argument("--every", type=int, default=30)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(Keyframe, MediaFile)
                .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
                .where(Keyframe.capture_id == args.capture_id)
                .order_by(Keyframe.timestamp_ms)
            )
        )
    selected = rows[:: max(1, args.every)]
    if rows and rows[-1] not in selected:
        selected.append(rows[-1])
    for keyframe, media in selected:
        suffix = Path(media.original_filename or media.object_key).suffix or ".jpg"
        destination = args.output / f"{keyframe.timestamp_ms:09d}{suffix}"
        download_media_file(
            bucket=media.bucket,
            key=media.object_key,
            destination=str(destination),
        )
        print(destination)


if __name__ == "__main__":
    main()
