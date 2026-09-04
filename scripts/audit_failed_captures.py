from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
sys.path.insert(0, str(API_SRC))

from progress_api.db import SessionLocal
from progress_api.models.capture import (
    Capture,
    Keyframe,
    MediaFile,
    ProcessingJob,
)
from progress_api.models.project import Project
from progress_api.models.spatial import Floor
from progress_api.object_storage import (
    EXTERNAL_MEDIA_BUCKET,
    external_media_paths,
)


def resolve_external_source(object_key: str) -> Path | None:
    for root in external_media_paths():
        candidate = (root / Path(object_key)).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report failed and incomplete captures without modifying the database."
    )
    parser.add_argument("--project-id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        statement = (
            select(Capture, MediaFile, Floor, Project)
            .join(MediaFile, MediaFile.id == Capture.source_video_id)
            .join(Floor, Floor.id == Capture.start_floor_id)
            .join(Project, Project.id == Capture.project_id)
            .order_by(Capture.captured_at)
        )
        if args.project_id:
            statement = statement.where(Capture.project_id == uuid.UUID(args.project_id))

        records: list[dict[str, object]] = []
        for capture, media, floor, project in db.execute(statement):
            jobs = list(
                db.scalars(
                    select(ProcessingJob)
                    .where(ProcessingJob.capture_id == capture.id)
                    .order_by(ProcessingJob.created_at.desc())
                )
            )
            latest = jobs[0] if jobs else None
            if capture.status not in {
                "FAILED",
                "STITCHER_REQUIRED",
                "QUEUED",
                "RUNNING",
                "PROCESSING",
                "QUEUED_LOCALIZATION",
            } and not (latest and latest.status == "FAILED"):
                continue

            source_path = None
            source_exists: bool | None = None
            if media.bucket == EXTERNAL_MEDIA_BUCKET:
                resolved = resolve_external_source(media.object_key)
                source_exists = resolved is not None
                source_path = str(resolved) if resolved else None

            keyframe_count = db.scalar(
                select(func.count(Keyframe.id)).where(Keyframe.capture_id == capture.id)
            )
            records.append(
                {
                    "capture_id": str(capture.id),
                    "project": project.name,
                    "captured_at": capture.captured_at.isoformat(),
                    "floor": floor.name,
                    "capture_status": capture.status,
                    "dataset_split": capture.dataset_split,
                    "filename": media.original_filename,
                    "bucket": media.bucket,
                    "object_key": media.object_key,
                    "source_exists": source_exists,
                    "source_path": source_path,
                    "media_status": media.upload_status,
                    "keyframes": int(keyframe_count or 0),
                    "job_count": len(jobs),
                    "latest_job_id": str(latest.id) if latest else None,
                    "latest_job_type": latest.job_type if latest else None,
                    "latest_job_status": latest.status if latest else None,
                    "latest_job_attempt": latest.attempt_no if latest else None,
                    "error_code": latest.error_code if latest else None,
                    "error_message": latest.error_message if latest else None,
                }
            )

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return

    print(f"FAILED_OR_INCOMPLETE={len(records)}")
    for record in records:
        print(
            " | ".join(
                [
                    str(record["captured_at"]),
                    str(record["floor"]),
                    f"capture={record['capture_status']}",
                    f"job={record['latest_job_type']}:{record['latest_job_status']}",
                    f"attempt={record['latest_job_attempt']}",
                    f"source={record['source_exists']}",
                    f"keyframes={record['keyframes']}",
                    str(record["filename"]),
                ]
            )
        )
        if record["error_message"]:
            print(f"  ERROR: {record['error_message']}")


if __name__ == "__main__":
    main()
