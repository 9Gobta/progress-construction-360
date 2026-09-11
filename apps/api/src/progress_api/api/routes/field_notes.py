from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from progress_api.access import require_project_role
from progress_api.config import get_settings
from progress_api.dependencies import CurrentUser, DbSession
from progress_api.models import (
    Capture,
    FieldNote,
    FieldNoteAttachment,
    FieldNoteComment,
    Floor,
    Keyframe,
    MediaFile,
    ProjectMember,
    User,
)
from progress_api.object_storage import presign_get_object, upload_file
from progress_api.schemas.field_note import (
    FieldNoteAttachmentRead,
    FieldNoteCommentCreate,
    FieldNoteCommentRead,
    FieldNoteRead,
    FieldNoteUpdate,
    FieldNoteWrite,
)

router = APIRouter()
settings = get_settings()
EDIT_ROLES = {"admin", "sub_admin", "reviewer"}
ATTACHMENT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


def _scope(
    *,
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    keyframe_id: uuid.UUID,
    db: DbSession,
) -> tuple[Capture, Floor, Keyframe]:
    capture = db.scalar(
        select(Capture).where(Capture.id == capture_id, Capture.project_id == project_id)
    )
    floor = db.scalar(select(Floor).where(Floor.id == floor_id, Floor.project_id == project_id))
    keyframe = db.scalar(
        select(Keyframe)
        .join(Capture, Capture.id == Keyframe.capture_id)
        .where(
            Keyframe.id == keyframe_id,
            Keyframe.capture_id == capture_id,
            Capture.project_id == project_id,
        )
    )
    if capture is None or floor is None or keyframe is None:
        raise HTTPException(status_code=404, detail="ไม่พบ Capture ชั้น หรือภาพ 360 ที่เลือก")
    return capture, floor, keyframe


def _validate_assignee(project_id: uuid.UUID, assignee_id: uuid.UUID | None, db: DbSession) -> None:
    if assignee_id is None:
        return
    exists = db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == assignee_id,
        )
    )
    if exists is None:
        raise HTTPException(status_code=422, detail="ผู้รับผิดชอบต้องเป็นสมาชิกโครงการ")


def _read(row: FieldNote, db: DbSession) -> FieldNoteRead:
    capture, floor, keyframe = _scope(
        project_id=row.project_id,
        capture_id=row.capture_id,
        floor_id=row.floor_id,
        keyframe_id=row.keyframe_id,
        db=db,
    )
    image_media = db.get(MediaFile, keyframe.media_file_id)
    creator = db.get(User, row.created_by_id)
    assignee = db.get(User, row.assignee_id) if row.assignee_id else None
    comments = db.execute(
        select(FieldNoteComment, User)
        .join(User, User.id == FieldNoteComment.created_by_id)
        .where(FieldNoteComment.field_note_id == row.id)
        .order_by(FieldNoteComment.created_at.asc())
    ).all()
    attachment_rows = db.execute(
        select(FieldNoteAttachment, MediaFile)
        .join(MediaFile, MediaFile.id == FieldNoteAttachment.media_file_id)
        .where(FieldNoteAttachment.field_note_id == row.id)
        .order_by(FieldNoteAttachment.created_at.asc())
    ).all()
    try:
        tags = json.loads(row.tags_json)
    except (TypeError, json.JSONDecodeError):
        tags = []
    try:
        markup_paths = json.loads(row.markup_json)
    except (TypeError, json.JSONDecodeError):
        markup_paths = []
    return FieldNoteRead(
        id=row.id,
        project_id=row.project_id,
        capture_id=row.capture_id,
        capture_date=capture.captured_at,
        floor_id=row.floor_id,
        floor_name=floor.name,
        keyframe_id=row.keyframe_id,
        keyframe_timestamp_ms=keyframe.timestamp_ms,
        image_url=presign_get_object(key=image_media.object_key, expires_in=3600)
        if image_media
        else "",
        title=row.title,
        description=row.description,
        status=row.status,
        due_date=row.due_date,
        tags=tags,
        markup_paths=markup_paths,
        assignee_id=row.assignee_id,
        assignee_name=assignee.display_name if assignee else None,
        plan_x=row.plan_x,
        plan_y=row.plan_y,
        panorama_longitude=row.panorama_longitude,
        panorama_latitude=row.panorama_latitude,
        panorama_fov=row.panorama_fov,
        created_by_id=row.created_by_id,
        created_by_name=creator.display_name if creator else "ผู้ใช้เดิม",
        created_at=row.created_at,
        updated_at=row.updated_at,
        comments=[
            FieldNoteCommentRead(
                id=comment.id,
                body=comment.body,
                created_by_id=comment.created_by_id,
                created_by_name=author.display_name,
                created_at=comment.created_at,
            )
            for comment, author in comments
        ],
        attachments=[
            FieldNoteAttachmentRead(
                id=attachment.id,
                filename=media.original_filename or "ไฟล์แนบ",
                content_type=media.content_type,
                size_bytes=media.size_bytes,
                download_url=presign_get_object(key=media.object_key, expires_in=3600),
            )
            for attachment, media in attachment_rows
        ],
    )


@router.get("/{project_id}/field-notes", response_model=list[FieldNoteRead])
def list_field_notes(
    project_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    capture_id: uuid.UUID | None = None,
    floor_id: uuid.UUID | None = None,
    field_status: Annotated[list[str] | None, Query()] = None,
    assignee_id: uuid.UUID | None = None,
    due_before: date | None = None,
    tag: Annotated[list[str] | None, Query()] = None,
    q: str | None = None,
) -> list[FieldNoteRead]:
    require_project_role(db, project_id=project_id, user_id=user.id)
    statement = select(FieldNote).where(FieldNote.project_id == project_id)
    if capture_id:
        statement = statement.where(FieldNote.capture_id == capture_id)
    if floor_id:
        statement = statement.where(FieldNote.floor_id == floor_id)
    if field_status:
        statement = statement.where(FieldNote.status.in_(field_status))
    if assignee_id:
        statement = statement.where(FieldNote.assignee_id == assignee_id)
    if due_before:
        statement = statement.where(FieldNote.due_date <= due_before)
    rows = list(db.scalars(statement.order_by(FieldNote.updated_at.desc())))
    normalized_tags = {item.casefold() for item in (tag or [])}
    query = (q or "").strip().casefold()
    if normalized_tags:
        rows = [
            row
            for row in rows
            if normalized_tags.issubset(
                {str(item).casefold() for item in json.loads(row.tags_json)}
            )
        ]
    if query:
        rows = [
            row
            for row in rows
            if query in f"{row.title} {row.description or ''} {row.tags_json}".casefold()
        ]
    return [_read(row, db) for row in rows]


@router.post(
    "/{project_id}/field-notes", response_model=FieldNoteRead, status_code=status.HTTP_201_CREATED
)
def create_field_note(
    project_id: uuid.UUID, payload: FieldNoteWrite, db: DbSession, user: CurrentUser
) -> FieldNoteRead:
    require_project_role(db, project_id=project_id, user_id=user.id, allowed_roles=EDIT_ROLES)
    _scope(
        project_id=project_id,
        capture_id=payload.capture_id,
        floor_id=payload.floor_id,
        keyframe_id=payload.keyframe_id,
        db=db,
    )
    _validate_assignee(project_id, payload.assignee_id, db)
    row = FieldNote(
        project_id=project_id,
        capture_id=payload.capture_id,
        floor_id=payload.floor_id,
        keyframe_id=payload.keyframe_id,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        status=payload.status,
        due_date=payload.due_date,
        tags_json=json.dumps(payload.tags, ensure_ascii=False),
        assignee_id=payload.assignee_id,
        plan_x=payload.plan_x,
        plan_y=payload.plan_y,
        panorama_longitude=payload.panorama_longitude,
        panorama_latitude=payload.panorama_latitude,
        panorama_fov=payload.panorama_fov,
        created_by_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _read(row, db)


@router.patch("/{project_id}/field-notes/{note_id}", response_model=FieldNoteRead)
def update_field_note(
    project_id: uuid.UUID,
    note_id: uuid.UUID,
    payload: FieldNoteUpdate,
    db: DbSession,
    user: CurrentUser,
) -> FieldNoteRead:
    require_project_role(db, project_id=project_id, user_id=user.id, allowed_roles=EDIT_ROLES)
    row = db.scalar(
        select(FieldNote).where(FieldNote.id == note_id, FieldNote.project_id == project_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบบันทึกหน้างาน")
    values = payload.model_dump(exclude_unset=True)
    if "assignee_id" in values:
        _validate_assignee(project_id, values["assignee_id"], db)
    if "tags" in values:
        values["tags_json"] = json.dumps(values.pop("tags"), ensure_ascii=False)
    if "markup_paths" in values:
        values["markup_json"] = json.dumps(values.pop("markup_paths"))
    for key, value in values.items():
        setattr(row, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(row)
    return _read(row, db)


@router.post(
    "/{project_id}/field-notes/{note_id}/comments", response_model=FieldNoteRead, status_code=201
)
def add_field_note_comment(
    project_id: uuid.UUID,
    note_id: uuid.UUID,
    payload: FieldNoteCommentCreate,
    db: DbSession,
    user: CurrentUser,
) -> FieldNoteRead:
    require_project_role(db, project_id=project_id, user_id=user.id, allowed_roles=EDIT_ROLES)
    row = db.scalar(
        select(FieldNote).where(FieldNote.id == note_id, FieldNote.project_id == project_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบบันทึกหน้างาน")
    db.add(FieldNoteComment(field_note_id=row.id, body=payload.body.strip(), created_by_id=user.id))
    db.commit()
    db.refresh(row)
    return _read(row, db)


@router.post(
    "/{project_id}/field-notes/{note_id}/attachments", response_model=FieldNoteRead, status_code=201
)
def attach_field_note_file(
    project_id: uuid.UUID,
    note_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> FieldNoteRead:
    require_project_role(db, project_id=project_id, user_id=user.id, allowed_roles=EDIT_ROLES)
    row = db.scalar(
        select(FieldNote).where(FieldNote.id == note_id, FieldNote.project_id == project_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบบันทึกหน้างาน")
    content_type = (file.content_type or "").lower()
    if content_type not in ATTACHMENT_TYPES:
        raise HTTPException(status_code=415, detail="รองรับไฟล์ JPG, PNG, WebP และ PDF")
    suffix = os.path.splitext(file.filename or "attachment")[1][:10]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        temp_path = temp.name
        digest = hashlib.sha256()
        size = 0
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ATTACHMENT_BYTES:
                os.unlink(temp_path)
                raise HTTPException(status_code=413, detail="ไฟล์แนบต้องไม่เกิน 25 MB")
            digest.update(chunk)
            temp.write(chunk)
    media = MediaFile(
        project_id=project_id,
        media_kind="FIELD_NOTE_ATTACHMENT",
        bucket=settings.s3_bucket,
        object_key=f"projects/{project_id}/field-notes/{row.id}/{uuid.uuid4()}{suffix}",
        original_filename=os.path.basename(file.filename or "attachment"),
        content_type=content_type,
        size_bytes=size,
        checksum_sha256=digest.hexdigest(),
        upload_status="READY",
        created_by_id=user.id,
    )
    try:
        upload_file(key=media.object_key, source=temp_path, content_type=content_type)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    db.add(media)
    db.flush()
    db.add(FieldNoteAttachment(field_note_id=row.id, media_file_id=media.id, created_by_id=user.id))
    db.commit()
    db.refresh(row)
    return _read(row, db)
