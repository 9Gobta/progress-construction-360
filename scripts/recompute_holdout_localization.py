"""Re-run frozen holdout inference without allowing holdout path tuning."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from progress_api.db import SessionLocal
from progress_api.models import Capture, ProcessingJob
from progress_api.services.localization import localize_capture_job


def main() -> None:
    with SessionLocal() as db:
        captures = list(
            db.scalars(
                select(Capture)
                .where(Capture.dataset_split == "HOLDOUT_TEST")
                .order_by(Capture.captured_at)
            )
        )
        for capture in captures:
            job = ProcessingJob(
                capture_id=capture.id,
                job_type="LOCALIZE",
                status="QUEUED",
                progress_percent=0,
                attempt_no=1,
                idempotency_key=f"{capture.id}:holdout-localize:{uuid.uuid4()}",
                pipeline_version="stella-vslam-visual-graph-v1",
            )
            capture.status = "QUEUED_LOCALIZATION"
            db.add(job)
            db.commit()
            print(f"START {capture.captured_at.date()} {capture.id}", flush=True)
            result = localize_capture_job(db, job.id)
            print(f"DONE  {capture.captured_at.date()} {result}", flush=True)


if __name__ == "__main__":
    main()
