import sys

from celery import Celery

from progress_api.config import get_settings

settings = get_settings()

celery_app = Celery(
    "progress_construction",
    broker=settings.redis_url,
    backend=settings.celery_result_backend,
    include=["progress_api.worker_tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "progress_api.worker_tasks.system_ping": {"queue": "video_cpu"},
        "progress_api.worker_tasks.process_video": {"queue": "video_cpu"},
        "progress_api.worker_tasks.localize_capture": {"queue": "video_cpu"},
    },
)

# Celery's prefork/billiard semaphore implementation is unreliable on native Windows.
# Video jobs are intentionally processed one at a time on the development laptop.
if sys.platform == "win32":
    celery_app.conf.update(worker_pool="solo", worker_concurrency=1)
