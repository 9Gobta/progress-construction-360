from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path

from progress_api.config import get_settings
from progress_api.db import Base
from progress_api.models import Capture, Floor, MediaFile, ProcessingJob, Project, User
from progress_api.object_storage import ensure_bucket, get_s3_client, upload_file
from progress_api.services.video_pipeline import process_video_job
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def main(source_override: Path | None = None) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    project_id = uuid.uuid4()
    source_key = f"projects/{project_id}/captures/smoke/source/video.mp4"
    settings = get_settings()
    client = get_s3_client()
    ensure_bucket(client, settings.s3_bucket)
    try:
        with tempfile.TemporaryDirectory(prefix="pipeline-smoke-") as temporary:
            source = source_override or Path(temporary) / "source.mp4"
            if source_override is None:
                subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "testsrc2=size=640x320:rate=15",
                        "-t",
                        "2",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        str(source),
                    ],
                    check=True,
                    capture_output=True,
                )
            upload_file(key=source_key, source=str(source), content_type="video/mp4")
            with Session(engine, expire_on_commit=False) as db:
                user_id = uuid.uuid4()
                user = User(
                    id=user_id,
                    email=f"smoke-{uuid.uuid4()}@example.com",
                    display_name="Smoke Test",
                    password_hash="not-used",
                )
                project = Project(
                    id=project_id,
                    name="Pipeline Smoke",
                    timezone="Asia/Bangkok",
                    created_by_id=user_id,
                )
                floor = Floor(project_id=project_id, name="ชั้น 1", level_index=1)
                media = MediaFile(
                    project_id=project_id,
                    media_kind="VIDEO",
                    bucket=settings.s3_bucket,
                    object_key=source_key,
                    original_filename="source.mp4",
                    content_type="video/mp4",
                    size_bytes=source.stat().st_size,
                    upload_status="READY",
                    created_by_id=user_id,
                )
                db.add_all([user, project, floor, media])
                db.flush()
                capture = Capture(
                    project_id=project_id,
                    source_video_id=media.id,
                    captured_at=datetime.now(timezone.utc),
                    start_floor_id=floor.id,
                    start_x=0.5,
                    start_y=0.5,
                    status="QUEUED",
                    created_by_id=user_id,
                )
                db.add(capture)
                db.flush()
                job = ProcessingJob(
                    capture_id=capture.id,
                    job_type="VALIDATE_VIDEO",
                    status="QUEUED",
                    progress_percent=0,
                    attempt_no=1,
                    idempotency_key=f"{capture.id}:smoke",
                    pipeline_version="capture-v1",
                )
                db.add(job)
                db.commit()
                result = process_video_job(db, job.id)
                print(result)
                if result.get("status") != "SUCCEEDED" or result.get("keyframe_count", 0) < 1:
                    raise RuntimeError("Pipeline smoke test failed")
    finally:
        response = client.list_objects_v2(
            Bucket=settings.s3_bucket,
            Prefix=f"projects/{project_id}/",
        )
        for item in response.get("Contents", []):
            client.delete_object(Bucket=settings.s3_bucket, Key=item["Key"])
        engine.dispose()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--source", type=Path)
    arguments = parser.parse_args()
    main(arguments.source)
