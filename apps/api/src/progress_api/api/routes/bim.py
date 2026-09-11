from __future__ import annotations

import os
import re
import tempfile
import uuid
from decimal import Decimal
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from progress_api.access import require_project_role
from progress_api.config import get_settings
from progress_api.dependencies import CurrentUser, DbSession
from progress_api.models import BimViewpoint, Capture, Keyframe, MediaFile
from progress_api.object_storage import presign_get_object, upload_file
from progress_api.schemas.bim import (
    BimModelListRead,
    BimModelRead,
    BimViewpointRead,
    BimViewpointWrite,
)

router = APIRouter()
settings = get_settings()
MAX_IFC_BYTES = 1024 * 1024 * 1024
IFC_SCHEMA_PATTERN = re.compile(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", re.IGNORECASE)


def _bim_rows(project_id: uuid.UUID, db: DbSession) -> list[MediaFile]:
    return list(
        db.scalars(
            select(MediaFile)
            .where(
                MediaFile.project_id == project_id,
                MediaFile.media_kind == "BIM_IFC",
                MediaFile.upload_status == "READY",
            )
            .order_by(MediaFile.created_at.asc(), MediaFile.id.asc())
        )
    )


def _schema_from_header(header: bytes) -> str:
    match = IFC_SCHEMA_PATTERN.search(header)
    return match.group(1).decode("ascii", errors="replace") if match else "IFC"


def _schema_from_filename(filename: str | None) -> str:
    normalized = (filename or "").upper().replace("-", "").replace("_", "")
    if "IFC4X3" in normalized:
        return "IFC4X3"
    if "IFC4" in normalized:
        return "IFC4"
    if "IFC2X3" in normalized:
        return "IFC2X3"
    return "IFC"


def _read_model(row: MediaFile, *, version_no: int, schema: str | None = None) -> BimModelRead:
    return BimModelRead(
        id=row.id,
        project_id=row.project_id,
        name=row.original_filename or f"BIM รุ่น {version_no}",
        version_no=version_no,
        ifc_schema=schema or _schema_from_filename(row.original_filename),
        size_bytes=row.size_bytes,
        download_url=presign_get_object(key=row.object_key, expires_in=4 * 60 * 60),
        created_by_id=row.created_by_id,
        created_at=row.created_at,
    )


@router.get("/{project_id}/bim-models", response_model=BimModelListRead)
def list_bim_models(
    project_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> BimModelListRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    rows = _bim_rows(project_id, db)
    versions = [_read_model(row, version_no=index + 1) for index, row in enumerate(rows)]
    return BimModelListRead(active=versions[-1] if versions else None, versions=versions)


@router.get("/{project_id}/bim-models/{model_id}/file")
def download_bim_model(
    project_id: uuid.UUID,
    model_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    """Authorize an IFC download before redirecting the web proxy to storage."""
    require_project_role(db, project_id=project_id, user_id=user.id)
    row = db.get(MediaFile, model_id)
    if (
        row is None
        or row.project_id != project_id
        or row.media_kind != "BIM_IFC"
        or row.upload_status != "READY"
    ):
        raise HTTPException(status_code=404, detail="ไม่พบโมเดล BIM")
    return RedirectResponse(presign_get_object(key=row.object_key, expires_in=300), status_code=307)


def _require_model_and_keyframe(
    *, project_id: uuid.UUID, model_id: uuid.UUID, keyframe_id: uuid.UUID, db: DbSession
) -> None:
    model = db.get(MediaFile, model_id)
    keyframe = db.scalar(
        select(Keyframe)
        .join(Capture, Keyframe.capture_id == Capture.id)
        .where(Keyframe.id == keyframe_id, Capture.project_id == project_id)
    )
    if (
        model is None
        or model.project_id != project_id
        or model.media_kind != "BIM_IFC"
        or model.upload_status != "READY"
        or keyframe is None
    ):
        raise HTTPException(status_code=404, detail="ไม่พบโมเดล BIM หรือจุดวาร์ป")


def _viewpoint_read(row: BimViewpoint) -> BimViewpointRead:
    return BimViewpointRead(
        id=row.id,
        project_id=row.project_id,
        model_media_file_id=row.model_media_file_id,
        keyframe_id=row.keyframe_id,
        position_x=float(row.position_x),
        position_y=float(row.position_y),
        position_z=float(row.position_z),
        target_x=float(row.target_x),
        target_y=float(row.target_y),
        target_z=float(row.target_z),
        fov=float(row.fov),
        updated_by_id=row.updated_by_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/{project_id}/bim-models/{model_id}/viewpoints/{keyframe_id}",
    response_model=BimViewpointRead | None,
)
def get_bim_viewpoint(
    project_id: uuid.UUID,
    model_id: uuid.UUID,
    keyframe_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> BimViewpointRead | None:
    require_project_role(db, project_id=project_id, user_id=user.id)
    _require_model_and_keyframe(
        project_id=project_id, model_id=model_id, keyframe_id=keyframe_id, db=db
    )
    row = db.scalar(
        select(BimViewpoint).where(
            BimViewpoint.model_media_file_id == model_id,
            BimViewpoint.keyframe_id == keyframe_id,
        )
    )
    return _viewpoint_read(row) if row else None


@router.put(
    "/{project_id}/bim-models/{model_id}/viewpoints/{keyframe_id}",
    response_model=BimViewpointRead,
)
def save_bim_viewpoint(
    project_id: uuid.UUID,
    model_id: uuid.UUID,
    keyframe_id: uuid.UUID,
    payload: BimViewpointWrite,
    db: DbSession,
    user: CurrentUser,
) -> BimViewpointRead:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin", "sub_admin", "reviewer"},
    )
    _require_model_and_keyframe(
        project_id=project_id, model_id=model_id, keyframe_id=keyframe_id, db=db
    )
    row = db.scalar(
        select(BimViewpoint).where(
            BimViewpoint.model_media_file_id == model_id,
            BimViewpoint.keyframe_id == keyframe_id,
        )
    )
    values = {
        field: Decimal(str(getattr(payload, field)))
        for field in (
            "position_x", "position_y", "position_z",
            "target_x", "target_y", "target_z", "fov",
        )
    }
    if row is None:
        row = BimViewpoint(
            project_id=project_id,
            model_media_file_id=model_id,
            keyframe_id=keyframe_id,
            updated_by_id=user.id,
            **values,
        )
        db.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
        row.updated_by_id = user.id
    db.commit()
    db.refresh(row)
    return _viewpoint_read(row)


@router.post(
    "/{project_id}/bim-models",
    response_model=BimModelRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_bim_model(
    project_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> BimModelRead:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin"},
    )
    filename = PurePath(file.filename or "").name
    if not filename or PurePath(filename).suffix.lower() != ".ifc":
        raise HTTPException(status_code=422, detail="รองรับเฉพาะไฟล์ .ifc")

    temp_path: str | None = None
    try:
        size_bytes = 0
        header = bytearray()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as temporary:
            temp_path = temporary.name
            while chunk := file.file.read(8 * 1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > MAX_IFC_BYTES:
                    raise HTTPException(status_code=413, detail="ไฟล์ IFC ต้องมีขนาดไม่เกิน 1 GB")
                if len(header) < 2 * 1024 * 1024:
                    header.extend(chunk[: 2 * 1024 * 1024 - len(header)])
                temporary.write(chunk)

        normalized_header = bytes(header).lstrip()
        if (
            not normalized_header.startswith(b"ISO-10303-21")
            or b"FILE_SCHEMA" not in normalized_header
        ):
            raise HTTPException(status_code=422, detail="ไฟล์นี้ไม่ใช่ IFC STEP ที่สมบูรณ์")

        media_id = uuid.uuid4()
        object_key = f"projects/{project_id}/bim/{media_id}/{filename}"
        upload_file(
            key=object_key,
            source=temp_path,
            content_type="application/x-step",
        )
        row = MediaFile(
            id=media_id,
            project_id=project_id,
            media_kind="BIM_IFC",
            bucket=settings.s3_bucket,
            object_key=object_key,
            original_filename=filename,
            content_type="application/x-step",
            size_bytes=size_bytes,
            upload_status="READY",
            created_by_id=user.id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        version_no = len(_bim_rows(project_id, db))
        return _read_model(
            row,
            version_no=version_no,
            schema=_schema_from_header(bytes(header)),
        )
    finally:
        file.file.close()
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
