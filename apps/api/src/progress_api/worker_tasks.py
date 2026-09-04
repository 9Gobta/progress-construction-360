import uuid
from typing import Any

from progress_api.db import SessionLocal
from progress_api.services.insta360_stitching import Insta360StitcherUnavailable
from progress_api.services.localization import localize_capture_job
from progress_api.services.video_pipeline import process_video_job
from progress_api.worker import celery_app


@celery_app.task(name="progress_api.worker_tasks.system_ping")
def system_ping() -> dict[str, Any]:
    """Small task used to verify broker and worker connectivity."""
    return {"status": "ok", "worker": "progress-construction"}


@celery_app.task(name="progress_api.worker_tasks.process_video", bind=True, max_retries=2)
def process_video(self, job_id: str) -> dict[str, object]:
    try:
        with SessionLocal() as db:
            return process_video_job(db, uuid.UUID(job_id))
    except Insta360StitcherUnavailable:
        raise
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc


@celery_app.task(name="progress_api.worker_tasks.localize_capture", bind=True, max_retries=2)
def localize_capture(self, job_id: str) -> dict[str, object]:
    try:
        with SessionLocal() as db:
            return localize_capture_job(db, uuid.UUID(job_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc
