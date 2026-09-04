from __future__ import annotations

import argparse
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from progress_api.config import get_settings
from progress_api.db import SessionLocal
from progress_api.models import (
    Capture,
    Floor,
    MediaFile,
    ProcessingJob,
    Project,
    ProjectMember,
)
from progress_api.object_storage import (
    EXTERNAL_MEDIA_BUCKET,
    delete_object,
    ensure_bucket,
    external_media_paths,
    get_s3_client,
    object_size,
    upload_capacity,
    upload_file,
)
from progress_api.services.video_pipeline import dispatch_video_job
from sqlalchemy import select

LONG_DATE_PATTERN = re.compile(r"(?:19|20|25)\d{6}")
SHORT_DATE_PATTERN = re.compile(r"(?<!\d)\d{6}(?!\d)")
FLOOR_PATTERN = re.compile(r"ชั้น\s*(-?\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class ImportCandidate:
    source: Path
    captured_at: datetime
    floor_index: int


def parse_candidate(path: Path, capture_hour: int) -> ImportCandidate | None:
    date_match = LONG_DATE_PATTERN.search(path.stem) or SHORT_DATE_PATTERN.search(
        path.stem
    )
    floor_matches = FLOOR_PATTERN.findall(path.stem)
    if date_match is None or not floor_matches:
        return None
    date_text = date_match.group(0)
    if len(date_text) == 8:
        year = int(date_text[:4])
        gregorian_year = year - 543 if year >= 2400 else year
        month = int(date_text[4:6])
        day = int(date_text[6:8])
    else:
        thai_short_year = int(date_text[:2])
        gregorian_year = 1957 + thai_short_year
        month = int(date_text[2:4])
        day = int(date_text[4:6])
    captured_at = datetime(
        gregorian_year,
        month,
        day,
        capture_hour,
        0,
        0,
        tzinfo=ZoneInfo("Asia/Bangkok"),
    )
    return ImportCandidate(
        source=path,
        captured_at=captured_at,
        floor_index=int(floor_matches[-1]),
    )


def nearest_ready_capture(
    references: list[Capture], *, target_date: date
) -> Capture | None:
    if not references:
        return None
    return min(
        references,
        key=lambda capture: abs((capture.captured_at.date() - target_date).days),
    )


def gib(value: int) -> str:
    return f"{value / 1024**3:.2f} GB"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import local stitched MP4 captures without browser upload overhead."
    )
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--project-id", required=True, type=uuid.UUID)
    parser.add_argument("--capture-hour", type=int, default=10)
    parser.add_argument(
        "--max-source-gb",
        type=float,
        default=None,
        help="Import only the earliest new files whose cumulative size fits this limit.",
    )
    parser.add_argument(
        "--link-source",
        action="store_true",
        help="Keep original videos under EXTERNAL_MEDIA_ROOT instead of copying to S3.",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    external_roots = external_media_paths()
    if args.link_source and not external_roots:
        raise SystemExit("--link-source requires EXTERNAL_MEDIA_ROOT or EXTERNAL_MEDIA_ROOTS")

    # The external SSD also contains MinIO data and a working copy of the app.
    # Recursing through those directories makes an import appear to hang and can
    # traverse hundreds of thousands of generated files. Production captures are
    # stored in YYMMDD folders directly below the selected source directory, so
    # limit discovery to those folders when they are present.
    date_directories = [
        path
        for path in args.source_dir.iterdir()
        if path.is_dir() and re.fullmatch(r"\d{6}", path.name)
    ]
    video_paths = (
        (video for directory in date_directories for video in directory.glob("*.mp4"))
        if date_directories
        else args.source_dir.rglob("*.mp4")
    )
    candidates = sorted(
        filter(
            None,
            (
                parse_candidate(path, args.capture_hour)
                for path in video_paths
            ),
        ),
        key=lambda item: item.captured_at,
    )
    if not candidates:
        raise SystemExit("No MP4 filename matched YYMMDD ... ชั้นN.mp4")

    with SessionLocal() as db:
        project = db.get(Project, args.project_id)
        if project is None:
            raise SystemExit(f"Project {args.project_id} was not found")
        membership = db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.role == "admin",
            )
        )
        if membership is None:
            raise SystemExit("Project has no admin member")

        floors = {
            floor.level_index: floor
            for floor in db.scalars(select(Floor).where(Floor.project_id == project.id))
        }
        reference_by_floor = {
            floor_index: list(
                db.scalars(
                    select(Capture).where(
                        Capture.project_id == project.id,
                        Capture.start_floor_id == floor.id,
                        Capture.status == "READY",
                        Capture.dataset_split == "DEVELOPMENT",
                    )
                )
            )
            for floor_index, floor in floors.items()
        }

        existing_keys = {
            (capture.captured_at.date(), capture.start_floor_id)
            for capture in db.scalars(
                select(Capture).where(Capture.project_id == project.id)
            )
        }
        unique_candidates: list[ImportCandidate] = []
        duplicate_files: list[ImportCandidate] = []
        candidate_keys: set[tuple[date, int]] = set()
        for item in candidates:
            key = (item.captured_at.date(), item.floor_index)
            if key in candidate_keys:
                duplicate_files.append(item)
                continue
            candidate_keys.add(key)
            unique_candidates.append(item)

        pending = [
            item
            for item in unique_candidates
            if (
                item.captured_at.date(),
                floors.get(item.floor_index).id if floors.get(item.floor_index) else None,
            )
            not in existing_keys
        ]
        skipped = [item for item in unique_candidates if item not in pending]
        pending_before_limit = list(pending)
        if args.max_source_gb is not None:
            limit_bytes = int(args.max_source_gb * 1024**3)
            selected: list[ImportCandidate] = []
            selected_bytes = 0
            for item in pending:
                item_bytes = item.source.stat().st_size
                if selected_bytes + item_bytes > limit_bytes:
                    break
                selected.append(item)
                selected_bytes += item_bytes
            pending = selected
        total_bytes = sum(item.source.stat().st_size for item in pending)
        print(f"Project: {project.name}", flush=True)
        print(
            f"Candidates: {len(candidates)}, pending: {len(pending_before_limit)}, "
            f"selected: {len(pending)}, skipped: {len(skipped)}",
            flush=True,
        )
        print(f"New source size: {gib(total_bytes)}", flush=True)
        print(
            "Storage mode: external link" if args.link_source else "Storage mode: S3 upload",
            flush=True,
        )
        for item in skipped:
            print(f"SKIP existing date {item.captured_at.date()}: {item.source.name}", flush=True)
        for item in duplicate_files:
            print(
                f"SKIP duplicate date/floor {item.captured_at.date()} "
                f"floor={item.floor_index}: {item.source}",
                flush=True,
            )
        for item in pending:
            floor = floors.get(item.floor_index)
            if floor is None:
                raise SystemExit(f"Floor index {item.floor_index} does not exist")
            reference = nearest_ready_capture(
                reference_by_floor.get(item.floor_index, []),
                target_date=item.captured_at.date(),
            )
            reference_label = reference.captured_at.date().isoformat() if reference else "none"
            print(
                f"PLAN {item.captured_at.date()} floor={floor.name} "
                f"size={gib(item.source.stat().st_size)} start-reference={reference_label}",
                flush=True,
            )

        if not args.execute:
            print("Dry run only. Add --execute to import.", flush=True)
            return

        if not args.link_source:
            allowed, required_bytes, disk = upload_capacity(file_size_bytes=total_bytes)
            if not allowed:
                free_label = gib(disk.free_bytes) if disk else "unknown"
                raise SystemExit(
                    f"Insufficient processing space: free={free_label}, "
                    f"required={gib(required_bytes)}"
                )

        ensure_bucket(get_s3_client(), settings.s3_bucket)
        queued_jobs: list[uuid.UUID] = []
        for position, item in enumerate(pending, start=1):
            floor = floors[item.floor_index]
            reference = nearest_ready_capture(
                reference_by_floor.get(item.floor_index, []),
                target_date=item.captured_at.date(),
            )
            start_x = reference.start_x if reference else 0.5
            start_y = reference.start_y if reference else 0.5
            reference_label = reference.captured_at.date().isoformat() if reference else "ไม่มี"
            media_id = uuid.uuid4()
            capture_id = uuid.uuid4()
            if args.link_source:
                resolved_source = item.source.resolve()
                source_root = next(
                    (root for root in external_roots if resolved_source.is_relative_to(root)),
                    None,
                )
                if source_root is None:
                    raise SystemExit(
                        f"Source is outside configured external media roots: {resolved_source}"
                    )
                object_key = resolved_source.relative_to(source_root).as_posix()
            else:
                object_key = (
                    f"projects/{project.id}/captures/{media_id}/source/video.mp4"
                )
            print(
                f"UPLOAD {position}/{len(pending)} {item.source.name} ({gib(item.source.stat().st_size)})",
                flush=True,
            )
            try:
                source_size = item.source.stat().st_size
                if not args.link_source:
                    upload_file(
                        key=object_key,
                        source=str(item.source),
                        content_type="video/mp4",
                    )
                    if object_size(key=object_key) != source_size:
                        raise RuntimeError(
                            "Uploaded object size does not match the source file"
                        )

                media = MediaFile(
                    id=media_id,
                    project_id=project.id,
                    media_kind="VIDEO",
                    bucket=(
                        EXTERNAL_MEDIA_BUCKET if args.link_source else settings.s3_bucket
                    ),
                    object_key=object_key,
                    original_filename=item.source.name,
                    content_type="video/mp4",
                    size_bytes=source_size,
                    upload_status="READY",
                    created_by_id=membership.user_id,
                )
                capture = Capture(
                    id=capture_id,
                    project_id=project.id,
                    source_video_id=media.id,
                    captured_at=item.captured_at,
                    captured_by_text="Insta360 X5 / เชื่อมไฟล์จาก External SSD",
                    start_floor_id=floor.id,
                    start_x=start_x,
                    start_y=start_y,
                    notes=(
                        "นำเข้าจาก External SSD; จุดเริ่มต้นคัดลอกจาก Capture "
                        f"วันที่ {reference_label} กรุณาตรวจสอบก่อนปรับเส้นทาง"
                    ),
                    dataset_split="DEVELOPMENT",
                    status="QUEUED",
                    created_by_id=membership.user_id,
                )
                job = ProcessingJob(
                    capture_id=capture.id,
                    job_type="VALIDATE_VIDEO",
                    status="QUEUED",
                    progress_percent=0,
                    attempt_no=1,
                    idempotency_key=f"{capture.id}:validate-video:{media.id}",
                    pipeline_version="capture-v1",
                )
                # Flush each parent before its dependent row. The operational
                # import does not construct ORM relationships, so explicit
                # ordering keeps SQLite foreign-key enforcement deterministic.
                db.add(media)
                db.flush()
                db.add(capture)
                db.flush()
                db.add(job)
                db.commit()
                queued_jobs.append(job.id)
                existing_keys.add((item.captured_at.date(), floor.id))
                print(f"IMPORTED {item.captured_at.date()} capture={capture.id}", flush=True)
            except Exception:
                db.rollback()
                if not args.link_source:
                    try:
                        delete_object(key=object_key)
                    except Exception as cleanup_error:  # noqa: BLE001
                        print(f"CLEANUP WARNING {object_key}: {cleanup_error}", flush=True)
                raise

        for job_id in queued_jobs:
            try:
                dispatch_video_job(job_id)
            except Exception as error:  # noqa: BLE001
                print(f"QUEUE WARNING {job_id}: {error}", flush=True)
        print(f"DONE imported={len(queued_jobs)} queued={len(queued_jobs)}", flush=True)


if __name__ == "__main__":
    main()
