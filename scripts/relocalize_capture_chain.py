"""Re-localize existing capture trajectories against trusted 3-D references.

The script processes captures chronologically so that a successful day becomes
an eligible reference for the next day.  HOLDOUT_TEST captures are excluded by
default to preserve the research evaluation split.

Examples::

    python scripts/relocalize_capture_chain.py --floor 1 --after 2026-01-20 --dry-run
    python scripts/relocalize_capture_chain.py --floor 1 --after 2026-01-20 --limit 5
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from progress_api.db import SessionLocal
from progress_api.models import (
    CameraPose,
    Capture,
    Floor,
    Keyframe,
    ProcessingJob,
)
from progress_api.services.localization import localize_capture_job

TRUSTED_ALGORITHM_MARKERS = (
    "dev-gt-piecewise-v1",
    "persistent-map-v1:",
    "previous-hloc-sfm-v1:",
)


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _day_end(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _algorithm(db, capture_id: uuid.UUID) -> str | None:
    return db.scalar(
        select(CameraPose.algorithm)
        .join(Keyframe, CameraPose.keyframe_id == Keyframe.id)
        .where(Keyframe.capture_id == capture_id)
        .limit(1)
    )


def _is_trusted(algorithm: str | None) -> bool:
    return bool(
        algorithm and any(marker in algorithm for marker in TRUSTED_ALGORITHM_MARKERS)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair plan routes chronologically using HLoc 3-D references."
    )
    parser.add_argument("--floor", type=int, required=True, help="Floor number")
    parser.add_argument("--after", type=date.fromisoformat)
    parser.add_argument("--before", type=date.fromisoformat)
    parser.add_argument("--limit", type=int, default=0, help="0 means no limit")
    parser.add_argument("--force", action="store_true", help="Re-run trusted captures")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        floor = db.scalar(select(Floor).where(Floor.level_index == args.floor))
        if floor is None:
            raise SystemExit(f"Floor {args.floor} was not found")

        statement = (
            select(Capture)
            .where(
                Capture.start_floor_id == floor.id,
                Capture.dataset_split == "DEVELOPMENT",
            )
            .order_by(Capture.captured_at, Capture.id)
        )
        if args.after:
            statement = statement.where(Capture.captured_at > _day_end(args.after))
        if args.before:
            statement = statement.where(Capture.captured_at < _day_start(args.before))

        candidates: list[tuple[Capture, str | None]] = []
        for capture in db.scalars(statement):
            algorithm = _algorithm(db, capture.id)
            if not args.force and _is_trusted(algorithm):
                continue
            candidates.append((capture, algorithm))
            if args.limit and len(candidates) >= args.limit:
                break

        if not candidates:
            print("No captures require relocalization.")
            return

        for capture, algorithm in candidates:
            print(
                f"PLAN {capture.captured_at.isoformat()} {capture.id} "
                f"status={capture.status} algorithm={algorithm or '-'}"
            )
        if args.dry_run:
            return

        failures = 0
        for capture, _algorithm_before in candidates:
            attempt = (
                int(
                    db.scalar(
                        select(ProcessingJob.attempt_no)
                        .where(ProcessingJob.capture_id == capture.id)
                        .order_by(ProcessingJob.created_at.desc())
                        .limit(1)
                    )
                    or 0
                )
                + 1
            )
            job = ProcessingJob(
                capture_id=capture.id,
                job_type="LOCALIZE",
                status="QUEUED",
                progress_percent=0,
                attempt_no=attempt,
                idempotency_key=f"{capture.id}:hloc-chain:{uuid.uuid4()}",
                pipeline_version="stella-hloc-sfm-v2",
            )
            capture.status = "QUEUED_LOCALIZATION"
            db.add(job)
            db.commit()
            print(
                f"RUN  {capture.captured_at.date()} capture={capture.id} job={job.id}"
            )
            try:
                result = localize_capture_job(db, job.id)
            except Exception as exc:  # noqa: BLE001 - continue the repair batch
                failures += 1
                print(f"FAIL {capture.captured_at.date()} {type(exc).__name__}: {exc}")
                continue

            db.refresh(capture)
            algorithm_after = _algorithm(db, capture.id)
            trusted = _is_trusted(algorithm_after)
            print(
                f"DONE {capture.captured_at.date()} status={capture.status} "
                f"trusted={trusted} poses={result.get('pose_count', 0)} "
                f"algorithm={algorithm_after or '-'}"
            )

        if failures:
            raise SystemExit(f"Completed with {failures} failed capture(s)")


if __name__ == "__main__":
    main()
