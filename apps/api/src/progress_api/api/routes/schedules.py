from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from progress_api.access import require_project_role
from progress_api.config import get_settings
from progress_api.dependencies import CurrentUser, DbSession
from progress_api.models import Activity, MediaFile, Project, ScheduleVersion
from progress_api.object_storage import delete_object, put_object
from progress_api.schemas.schedule import (
    ActivityRead,
    SchedulePreviewActivity,
    SchedulePreviewRead,
    ScheduleVersionRead,
)
from progress_api.services.schedule_import import ScheduleImportError, load_schedule_workbook

router = APIRouter()
settings = get_settings()
MAX_SCHEDULE_BYTES = 20 * 1024 * 1024
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _read_xlsx(upload: UploadFile) -> bytes:
    filename = upload.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=422, detail="รองรับเฉพาะไฟล์ .xlsx")
    content = await upload.read(MAX_SCHEDULE_BYTES + 1)
    if not content or len(content) > MAX_SCHEDULE_BYTES:
        raise HTTPException(status_code=422, detail="ไฟล์ต้องมีขนาดไม่เกิน 20 MB")
    return content


def _parse_preview(filename: str, content: bytes) -> SchedulePreviewRead:
    try:
        result = load_schedule_workbook(content)
    except (ScheduleImportError, ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SchedulePreviewRead(
        filename=filename,
        checksum=hashlib.sha256(content).hexdigest(),
        sheet_name=result.sheet_name,
        row_count=len(result.rows),
        used_baseline_dates=result.used_baseline_dates,
        warnings=list(result.warnings),
        activities=[SchedulePreviewActivity.model_validate(row.__dict__) for row in result.rows],
    )


@router.post("/{project_id}/schedules/preview", response_model=SchedulePreviewRead)
async def preview_schedule(
    project_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
    db: DbSession,
    user: CurrentUser,
) -> SchedulePreviewRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin"}
    )
    content = await _read_xlsx(file)
    return _parse_preview(file.filename or "schedule.xlsx", content)


@router.post(
    "/{project_id}/schedules/import",
    response_model=ScheduleVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def import_schedule(
    project_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
    db: DbSession,
    user: CurrentUser,
    name: Annotated[str, Form(min_length=1, max_length=200)],
    is_baseline: Annotated[bool, Form()] = True,
) -> ScheduleVersion:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin"}
    )
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="ไม่พบโครงการ")
    content = await _read_xlsx(file)
    preview = _parse_preview(file.filename or "schedule.xlsx", content)
    duplicate = db.scalar(
        select(ScheduleVersion.id).where(
            ScheduleVersion.project_id == project_id,
            ScheduleVersion.checksum == preview.checksum,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Schedule ไฟล์นี้ถูกนำเข้าแล้ว")

    version_no = (
        db.scalar(
            select(func.coalesce(func.max(ScheduleVersion.version_no), 0)).where(
                ScheduleVersion.project_id == project_id
            )
        )
        or 0
    ) + 1
    version_id = uuid.uuid4()
    media_id = uuid.uuid4()
    object_key = f"projects/{project_id}/schedules/{version_id}/source/schedule.xlsx"
    put_object(key=object_key, body=content, content_type=XLSX_CONTENT_TYPE)

    try:
        if is_baseline:
            db.execute(
                update(ScheduleVersion)
                .where(ScheduleVersion.project_id == project_id)
                .values(is_baseline=False)
            )
        media = MediaFile(
            id=media_id,
            project_id=project_id,
            media_kind="SCHEDULE",
            bucket=settings.s3_bucket,
            object_key=object_key,
            original_filename=file.filename,
            content_type=XLSX_CONTENT_TYPE,
            size_bytes=len(content),
            checksum_sha256=preview.checksum,
            upload_status="READY",
            created_by_id=user.id,
        )
        schedule = ScheduleVersion(
            id=version_id,
            project_id=project_id,
            name=name.strip(),
            version_no=version_no,
            source_type="XLSX",
            source_media_file_id=media_id,
            is_baseline=is_baseline,
            imported_by_id=user.id,
            row_count=preview.row_count,
            checksum=preview.checksum,
            status="READY",
        )
        # Persist the dependency chain in explicit stages.  The production
        # SQLite database enforces foreign keys, and a single ORM flush with
        # MediaFile, ScheduleVersion and self-referencing Activity rows can
        # otherwise batch the children before every referenced row exists.
        # (The preview endpoint is unaffected, which made the failure appear
        # only after the user confirmed the import.)
        db.add(media)
        db.flush()
        db.add(schedule)
        db.flush()

        timezone = ZoneInfo(project.timezone)
        activity_ids = {row.wbs: uuid.uuid4() for row in preview.activities}
        for row in preview.activities:
            planned_start = row.planned_start.replace(tzinfo=timezone).astimezone(ZoneInfo("UTC"))
            planned_finish = row.planned_finish.replace(tzinfo=timezone).astimezone(ZoneInfo("UTC"))
            db.add(
                Activity(
                    id=activity_ids[row.wbs],
                    schedule_version_id=version_id,
                    parent_activity_id=activity_ids.get(row.parent_wbs or ""),
                    wbs=row.wbs,
                    name=row.name,
                    planned_start=planned_start,
                    planned_finish=planned_finish,
                    percent_complete_source=None,
                    is_summary=row.is_summary,
                    source_row_no=row.source_row_no,
                    created_at=datetime.now(ZoneInfo("UTC")),
                )
            )
        db.flush()
        db.commit()
    except (IntegrityError, ValueError):
        db.rollback()
        delete_object(key=object_key)
        raise HTTPException(status_code=409, detail="ไม่สามารถบันทึก Schedule Version ได้") from None
    db.refresh(schedule)
    return schedule


@router.get("/{project_id}/schedules", response_model=list[ScheduleVersionRead])
def list_schedules(
    project_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[ScheduleVersion]:
    require_project_role(db, project_id=project_id, user_id=user.id)
    return list(
        db.scalars(
            select(ScheduleVersion)
            .where(ScheduleVersion.project_id == project_id)
            .order_by(ScheduleVersion.version_no.desc())
        )
    )


@router.get(
    "/{project_id}/schedules/{schedule_id}/activities",
    response_model=list[ActivityRead],
)
def list_activities(
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> list[Activity]:
    require_project_role(db, project_id=project_id, user_id=user.id)
    schedule = db.get(ScheduleVersion, schedule_id)
    if schedule is None or schedule.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบ Schedule Version")
    return list(
        db.scalars(
            select(Activity)
            .where(Activity.schedule_version_id == schedule_id)
            .order_by(Activity.source_row_no)
        )
    )
