import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Annotated

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from progress_api.access import require_project_role
from progress_api.config import get_settings
from progress_api.dependencies import CurrentUser, DbSession
from progress_api.models import (
    BeamProgressEntry,
    BeamSegment,
    Floor,
    MediaFile,
    Sheet,
    StructuralElement,
)
from progress_api.object_storage import download_object, presign_get_object, put_object
from progress_api.schemas.spatial import (
    BeamSegmentLengthUpdate,
    BeamSegmentRead,
    BeamSegmentSetRequest,
    FloorCreate,
    FloorPlanInfo,
    FloorPlanPageRequest,
    FloorRead,
    StructuralElementAreaUpdate,
    StructuralElementRead,
)
from progress_api.services.temporary_workspace import temporary_workspace

router = APIRouter()
MAX_PLAN_BYTES = 50 * 1024 * 1024
PLAN_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _active_plan_sheet(db: DbSession, floor_id: uuid.UUID) -> Sheet | None:
    return db.scalar(
        select(Sheet)
        .where(
            Sheet.floor_id == floor_id,
            Sheet.sheet_type == "STRUCTURAL",
            Sheet.is_active.is_(True),
            Sheet.preview_media_file_id.is_not(None),
        )
        .order_by(Sheet.updated_at.desc())
    )


def _floor_read(db: DbSession, floor: Floor) -> FloorRead:
    return FloorRead.model_validate(floor).model_copy(
        update={"has_plan": _active_plan_sheet(db, floor.id) is not None}
    )


def _pdf_page_count(source: Path) -> int:
    executable = shutil.which("pdfinfo")
    if not executable:
        raise HTTPException(status_code=503, detail="Server ยังไม่มี pdfinfo")
    try:
        result = subprocess.run(
            [executable, str(source)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=422, detail="อ่านจำนวนหน้า PDF ไม่สำเร็จ") from exc
    for line in result.stdout.splitlines():
        if line.lower().startswith("pages:"):
            return max(1, int(line.split(":", 1)[1].strip()))
    raise HTTPException(status_code=422, detail="ไม่พบจำนวนหน้าใน PDF")


def _plan_preview(
    data: bytes,
    content_type: str,
    filename: str,
    page_number: int = 1,
) -> tuple[bytes, int, int, int]:
    page_count = 1
    if content_type in PLAN_IMAGE_TYPES:
        if page_number != 1:
            raise HTTPException(status_code=422, detail="ไฟล์รูปภาพมีเพียงหน้าเดียว")
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    elif content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        executable = shutil.which("pdftoppm")
        if not executable:
            raise HTTPException(
                status_code=503,
                detail="เครื่อง Server ยังไม่มี pdftoppm กรุณาอัปโหลด PNG หรือ JPG",
            )
        with temporary_workspace(prefix="progress-plan-") as temporary:
            workspace = Path(temporary)
            source = workspace / "source.pdf"
            output = workspace / "preview"
            source.write_bytes(data)
            page_count = _pdf_page_count(source)
            if page_number > page_count:
                raise HTTPException(
                    status_code=422,
                    detail=f"PDF มี {page_count} หน้า ไม่สามารถเลือกหน้า {page_number} ได้",
                )
            try:
                subprocess.run(
                    [
                        executable,
                        "-png",
                        "-f",
                        str(page_number),
                        "-l",
                        str(page_number),
                        "-singlefile",
                        "-r",
                        "180",
                        str(source),
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                raise HTTPException(status_code=422, detail="แปลง PDF เป็นภาพไม่สำเร็จ") from exc
            image = cv2.imread(str(output.with_suffix(".png")), cv2.IMREAD_COLOR)
    else:
        raise HTTPException(
            status_code=415,
            detail="รองรับเฉพาะ PDF, PNG, JPG และ WebP",
        )
    if image is None or image.size == 0:
        raise HTTPException(status_code=422, detail="ไม่สามารถอ่านภาพแปลนได้")
    height, width = image.shape[:2]
    success, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not success:
        raise HTTPException(status_code=422, detail="สร้างภาพตัวอย่างแปลนไม่สำเร็จ")
    return encoded.tobytes(), int(width), int(height), page_count


@router.get("/{project_id}/floors", response_model=list[FloorRead])
def list_floors(project_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[FloorRead]:
    require_project_role(db, project_id=project_id, user_id=user.id)
    floors = list(
        db.scalars(
            select(Floor)
            .where(Floor.project_id == project_id)
            .order_by(Floor.level_index)
        )
    )
    return [_floor_read(db, floor) for floor in floors]


@router.post(
    "/{project_id}/floors",
    response_model=FloorRead,
    status_code=status.HTTP_201_CREATED,
)
def create_floor(
    project_id: uuid.UUID,
    payload: FloorCreate,
    db: DbSession,
    user: CurrentUser,
) -> FloorRead:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin"},
    )
    floor = Floor(
        project_id=project_id,
        name=payload.name.strip(),
        level_index=payload.level_index,
        elevation_m=payload.elevation_m,
        available_from=payload.available_from,
    )
    db.add(floor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ชื่อชั้นหรือลำดับชั้นซ้ำในโครงการ",
        ) from None
    db.refresh(floor)
    return _floor_read(db, floor)


@router.post(
    "/{project_id}/floors/{floor_id}/plan",
    response_model=FloorRead,
)
async def upload_floor_plan(
    project_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> FloorRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    floor = db.get(Floor, floor_id)
    if floor is None or floor.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบชั้นอาคาร")
    data = await file.read(MAX_PLAN_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="ไฟล์แปลนว่างเปล่า")
    if len(data) > MAX_PLAN_BYTES:
        raise HTTPException(status_code=413, detail="ไฟล์แปลนต้องมีขนาดไม่เกิน 50 MB")
    filename = Path(file.filename or "floor-plan").name
    content_type = (file.content_type or "application/octet-stream").lower()
    preview, width, height, page_count = _plan_preview(data, content_type, filename)
    revision = uuid.uuid4()
    suffix = Path(filename).suffix.lower() or ".bin"
    source_key = f"projects/{project_id}/floors/{floor_id}/plans/{revision}/source{suffix}"
    preview_key = f"projects/{project_id}/floors/{floor_id}/plans/{revision}/preview.png"
    put_object(key=source_key, body=data, content_type=content_type)
    put_object(key=preview_key, body=preview, content_type="image/png")
    source_media = MediaFile(
        project_id=project_id,
        media_kind="FLOOR_PLAN_SOURCE",
        bucket=get_settings().s3_bucket,
        object_key=source_key,
        original_filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        upload_status="READY",
        created_by_id=user.id,
    )
    preview_media = MediaFile(
        project_id=project_id,
        media_kind="FLOOR_PLAN_PREVIEW",
        bucket=get_settings().s3_bucket,
        object_key=preview_key,
        original_filename=f"{Path(filename).stem}.png",
        content_type="image/png",
        size_bytes=len(preview),
        upload_status="READY",
        created_by_id=user.id,
    )
    db.add_all([source_media, preview_media])
    db.flush()
    sheet = db.scalar(
        select(Sheet)
        .where(Sheet.floor_id == floor.id, Sheet.sheet_type == "STRUCTURAL")
        .order_by(Sheet.created_at)
    )
    if sheet is None:
        sheet = Sheet(floor_id=floor.id, name=f"แปลนโครงสร้าง{floor.name}", sheet_type="STRUCTURAL")
        db.add(sheet)
    sheet.source_media_file_id = source_media.id
    sheet.preview_media_file_id = preview_media.id
    sheet.width_px = width
    sheet.height_px = height
    sheet.page_number = 1
    sheet.page_count = page_count
    sheet.is_active = True
    db.commit()
    db.refresh(floor)
    return _floor_read(db, floor)


@router.get("/{project_id}/floors/{floor_id}/plan-url")
def get_floor_plan_url(
    project_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    require_project_role(db, project_id=project_id, user_id=user.id)
    floor = db.get(Floor, floor_id)
    if floor is None or floor.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบชั้นอาคาร")
    sheet = _active_plan_sheet(db, floor.id)
    media = db.get(MediaFile, sheet.preview_media_file_id) if sheet else None
    if media is None or media.upload_status != "READY":
        raise HTTPException(status_code=404, detail="ชั้นนี้ยังไม่มีแปลน")
    return {"url": presign_get_object(key=media.object_key, expires_in=300)}


@router.get(
    "/{project_id}/floors/{floor_id}/plan-info",
    response_model=FloorPlanInfo,
)
def get_floor_plan_info(
    project_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> FloorPlanInfo:
    require_project_role(db, project_id=project_id, user_id=user.id)
    floor = db.get(Floor, floor_id)
    if floor is None or floor.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบชั้นอาคาร")
    sheet = _active_plan_sheet(db, floor.id)
    source = db.get(MediaFile, sheet.source_media_file_id) if sheet else None
    if sheet is None or source is None or source.upload_status != "READY":
        raise HTTPException(status_code=404, detail="ชั้นนี้ยังไม่มีแปลน")
    return FloorPlanInfo(
        filename=source.original_filename,
        content_type=source.content_type,
        page_number=sheet.page_number,
        page_count=sheet.page_count,
        width_px=sheet.width_px,
        height_px=sheet.height_px,
    )


@router.patch(
    "/{project_id}/floors/{floor_id}/plan",
    response_model=FloorPlanInfo,
)
def select_floor_plan_page(
    project_id: uuid.UUID,
    floor_id: uuid.UUID,
    payload: FloorPlanPageRequest,
    db: DbSession,
    user: CurrentUser,
) -> FloorPlanInfo:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    floor = db.get(Floor, floor_id)
    if floor is None or floor.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบชั้นอาคาร")
    sheet = _active_plan_sheet(db, floor.id)
    source = db.get(MediaFile, sheet.source_media_file_id) if sheet else None
    preview_media = db.get(MediaFile, sheet.preview_media_file_id) if sheet else None
    if sheet is None or source is None or preview_media is None:
        raise HTTPException(status_code=404, detail="ชั้นนี้ยังไม่มีแปลน")
    if source.content_type != "application/pdf" and not (
        source.original_filename or ""
    ).lower().endswith(".pdf"):
        if payload.page_number != 1:
            raise HTTPException(status_code=422, detail="ไฟล์รูปภาพมีเพียงหน้าเดียว")
        return FloorPlanInfo(
            filename=source.original_filename,
            content_type=source.content_type,
            page_number=1,
            page_count=1,
        )
    with temporary_workspace(prefix="progress-plan-page-") as temporary:
        source_path = Path(temporary) / "source.pdf"
        download_object(key=source.object_key, destination=str(source_path))
        data = source_path.read_bytes()
    preview, width, height, page_count = _plan_preview(
        data,
        source.content_type,
        source.original_filename or "floor-plan.pdf",
        payload.page_number,
    )
    put_object(key=preview_media.object_key, body=preview, content_type="image/png")
    preview_media.size_bytes = len(preview)
    preview_media.original_filename = (
        f"{Path(source.original_filename or 'floor-plan').stem}-page-{payload.page_number}.png"
    )
    sheet.width_px = width
    sheet.height_px = height
    sheet.page_number = payload.page_number
    sheet.page_count = page_count
    db.commit()
    return FloorPlanInfo(
        filename=source.original_filename,
        content_type=source.content_type,
        page_number=sheet.page_number,
        page_count=sheet.page_count,
    )


@router.get(
    "/{project_id}/floors/{floor_id}/beam-segments",
    response_model=list[BeamSegmentRead],
)
def list_beam_segments(
    project_id: uuid.UUID, floor_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[BeamSegment]:
    require_project_role(db, project_id=project_id, user_id=user.id)
    floor = db.get(Floor, floor_id)
    if floor is None or floor.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบชั้นอาคาร")
    return list(
        db.scalars(
            select(BeamSegment)
            .join(Sheet, BeamSegment.sheet_id == Sheet.id)
            .where(Sheet.floor_id == floor_id, BeamSegment.is_active.is_(True))
            .order_by(BeamSegment.code)
        )
    )


@router.get(
    "/{project_id}/floors/{floor_id}/structural-elements",
    response_model=list[StructuralElementRead],
)
def list_structural_elements(
    project_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> list[StructuralElement]:
    require_project_role(db, project_id=project_id, user_id=user.id)
    floor = db.get(Floor, floor_id)
    if floor is None or floor.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบชั้นอาคาร")
    return list(
        db.scalars(
            select(StructuralElement)
            .where(
                StructuralElement.project_id == project_id,
                StructuralElement.floor_id == floor_id,
                StructuralElement.is_active.is_(True),
            )
            .order_by(StructuralElement.element_kind, StructuralElement.code)
        )
    )


@router.put(
    "/{project_id}/floors/{floor_id}/beam-segments",
    response_model=list[BeamSegmentRead],
)
def replace_beam_segments(
    project_id: uuid.UUID,
    floor_id: uuid.UUID,
    payload: BeamSegmentSetRequest,
    db: DbSession,
    user: CurrentUser,
) -> list[BeamSegment]:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin"}
    )
    floor = db.get(Floor, floor_id)
    if floor is None or floor.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบชั้นอาคาร")
    codes = [item.code.strip() for item in payload.segments]
    if len(set(codes)) != len(codes):
        raise HTTPException(status_code=422, detail="รหัสคานต้องไม่ซ้ำกัน")
    sheet = db.scalar(
        select(Sheet)
        .where(Sheet.floor_id == floor_id, Sheet.sheet_type == "STRUCTURAL")
        .order_by(Sheet.created_at)
    )
    if sheet is None:
        sheet = Sheet(
            floor_id=floor_id,
            name=payload.sheet_name.strip(),
            sheet_type="STRUCTURAL",
            is_active=True,
        )
        db.add(sheet)
        db.flush()
    existing = {
        segment.code: segment
        for segment in db.scalars(
            select(BeamSegment).where(BeamSegment.sheet_id == sheet.id)
        )
    }
    requested = set(codes)
    removed_with_history = [
        segment.id
        for code, segment in existing.items()
        if code not in requested
    ]
    protected_ids = set(db.scalars(
        select(BeamProgressEntry.beam_segment_id).where(
            BeamProgressEntry.beam_segment_id.in_(removed_with_history)
        )
    )) if removed_with_history else set()
    if protected_ids:
        protected_codes = sorted(
            code for code, segment in existing.items() if segment.id in protected_ids
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "เปลี่ยนแปลนไม่ได้เพราะคานต่อไปนี้มีประวัติ Progress แล้ว: "
                + ", ".join(protected_codes)
                + " กรุณาคงรหัสเดิมเพื่อเชื่อมประวัติ"
            ),
        )
    for code, segment in existing.items():
        if code not in requested:
            segment.is_active = False
    for item, code in zip(payload.segments, codes, strict=True):
        segment = existing.get(code)
        if segment is None:
            segment = BeamSegment(sheet_id=sheet.id, code=code)
            db.add(segment)
        segment.beam_type = item.beam_type
        segment.start_x = item.start_x
        segment.start_y = item.start_y
        segment.end_x = item.end_x
        segment.end_y = item.end_y
        segment.length_m = item.length_m
        segment.source = "MANUAL"
        segment.is_active = True
    db.commit()
    return list(
        db.scalars(
            select(BeamSegment)
            .where(BeamSegment.sheet_id == sheet.id, BeamSegment.is_active.is_(True))
            .order_by(BeamSegment.code)
        )
    )


@router.patch(
    "/{project_id}/floors/{floor_id}/beam-segments/{beam_segment_id}",
    response_model=BeamSegmentRead,
)
def update_beam_segment_length(
    project_id: uuid.UUID,
    floor_id: uuid.UUID,
    beam_segment_id: uuid.UUID,
    payload: BeamSegmentLengthUpdate,
    db: DbSession,
    user: CurrentUser,
) -> BeamSegment:
    """Correct one beam length without replacing any other plan geometry."""
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "sub_admin"}
    )
    segment = db.scalar(
        select(BeamSegment)
        .join(Sheet, BeamSegment.sheet_id == Sheet.id)
        .join(Floor, Sheet.floor_id == Floor.id)
        .where(
            BeamSegment.id == beam_segment_id,
            BeamSegment.is_active.is_(True),
            Floor.id == floor_id,
            Floor.project_id == project_id,
        )
    )
    if segment is None:
        raise HTTPException(status_code=404, detail="ไม่พบคานในชั้นที่เลือก")
    segment.length_m = payload.length_m
    segment.source = "MANUAL"
    db.commit()
    db.refresh(segment)
    return segment


@router.patch(
    "/{project_id}/floors/{floor_id}/structural-elements/{element_id}/area",
    response_model=StructuralElementRead,
)
def update_structural_element_area(
    project_id: uuid.UUID,
    floor_id: uuid.UUID,
    element_id: uuid.UUID,
    payload: StructuralElementAreaUpdate,
    db: DbSession,
    user: CurrentUser,
) -> StructuralElement:
    """Correct only the measurable slab area; identity and geometry stay locked."""
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "sub_admin"}
    )
    element = db.scalar(
        select(StructuralElement).where(
            StructuralElement.id == element_id,
            StructuralElement.project_id == project_id,
            StructuralElement.floor_id == floor_id,
            StructuralElement.element_kind == "SLAB",
            StructuralElement.is_active.is_(True),
        )
    )
    if element is None:
        raise HTTPException(status_code=404, detail="ไม่พบพื้นที่พื้นในชั้นที่เลือก")
    geometry = dict(element.geometry_json or {})
    geometry["area_m2"] = float(payload.area_m2)
    element.geometry_json = geometry
    element.source = "MANUAL"
    db.commit()
    db.refresh(element)
    return element
