from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from progress_api.db import SessionLocal
from progress_api.models.capture import (
    CameraPose,
    Capture,
    Keyframe,
    ProcessingJob,
)
from progress_api.models.spatial import Floor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True, type=uuid.UUID)
    args = parser.parse_args()

    with SessionLocal() as db:
        captures = list(
            db.scalars(
                select(Capture)
                .where(Capture.project_id == args.project_id)
                .order_by(Capture.captured_at)
            )
        )
        for capture in captures:
            floor = db.get(Floor, capture.start_floor_id)
            algorithms = list(
                db.execute(
                    select(CameraPose.algorithm, func.count(CameraPose.id))
                    .join(Keyframe, Keyframe.id == CameraPose.keyframe_id)
                    .where(Keyframe.capture_id == capture.id)
                    .group_by(CameraPose.algorithm)
                    .order_by(func.count(CameraPose.id).desc())
                )
            )
            latest_localization = db.scalar(
                select(ProcessingJob)
                .where(
                    ProcessingJob.capture_id == capture.id,
                    ProcessingJob.job_type == "LOCALIZE",
                )
                .order_by(ProcessingJob.created_at.desc())
                .limit(1)
            )
            algorithm_text = "; ".join(
                f"{algorithm} ({count})" for algorithm, count in algorithms
            ) or "NO_POSES"
            job_text = (
                f"{latest_localization.status}/{latest_localization.pipeline_version}"
                if latest_localization
                else "NO_LOCALIZE_JOB"
            )
            print(
                f"{capture.captured_at.date().isoformat()} | {floor.name if floor else '?'} | "
                f"{capture.id} | {capture.status} | {job_text} | {algorithm_text}"
            )


if __name__ == "__main__":
    main()
