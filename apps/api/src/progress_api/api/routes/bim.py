from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from sqlalchemy import select

from progress_api.access import require_project_role
from progress_api.config import get_settings
from progress_api.dependencies import CurrentUser, DbSession
from progress_api.models import MediaFile
from progress_api.object_storage import presign_get_object, upload_file
from progress_api.schemas.bim import BimModelListRead, BimModelRead

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
