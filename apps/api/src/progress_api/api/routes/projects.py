import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from progress_api.access import require_project_role
from progress_api.dependencies import CurrentUser, DbSession
from progress_api.models import Capture, ProcessingJob, Project, ProjectMember, User
from progress_api.object_storage import delete_objects_with_prefix
from progress_api.schemas.project import (
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectMemberUpdate,
    ProjectRead,
    ProjectScopeUpdate,
)

router = APIRouter()


def _read_project(project: Project, role: str) -> ProjectRead:
    result = ProjectRead.model_validate(project)
    return result.model_copy(update={"role": role})


@router.get("", response_model=list[ProjectRead])
def list_projects(db: DbSession, user: CurrentUser) -> list[ProjectRead]:
    rows = db.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user.id)
        .order_by(Project.updated_at.desc())
    ).all()
    return [_read_project(project, role) for project, role in rows]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: DbSession, user: CurrentUser) -> ProjectRead:
    project = Project(
        name=payload.name.strip(),
        location=payload.location.strip() if payload.location else None,
        timezone=payload.timezone,
        description=payload.description.strip() if payload.description else None,
        structural_tracking_end_date=payload.structural_tracking_end_date,
        created_by_id=user.id,
    )
    project.memberships.append(ProjectMember(user_id=user.id, role="admin"))
    db.add(project)
    db.commit()
    db.refresh(project)
    return _read_project(project, "admin")


@router.patch("/{project_id}/scope", response_model=ProjectRead)
def update_project_scope(
    project_id: uuid.UUID,
    payload: ProjectScopeUpdate,
    db: DbSession,
    user: CurrentUser,
) -> ProjectRead:
    role = require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin"},
    )
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบโครงการ")
    project.structural_tracking_end_date = payload.structural_tracking_end_date
    db.commit()
    db.refresh(project)
    return _read_project(project, role)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ProjectRead:
    row = db.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(Project.id == project_id, ProjectMember.user_id == user.id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบโครงการ")
    project, role = row
    return _read_project(project, role)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin"},
    )
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบโครงการ")
    active_job = db.scalar(
        select(ProcessingJob.id)
        .join(Capture, Capture.id == ProcessingJob.capture_id)
        .where(
            Capture.project_id == project_id,
            ProcessingJob.status.in_(["QUEUED", "RUNNING"]),
        )
    )
    if active_job is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="โครงการยังมี Capture ที่กำลังประมวลผล กรุณารอให้งานจบก่อนลบ",
        )

    db.delete(project)
    db.commit()
    try:
        delete_objects_with_prefix(prefix=f"projects/{project_id}/")
    except Exception:
        # The project is already gone from the database. A failed best-effort
        # object cleanup must not make the deleted project reappear.
        pass


def _member_read(member: ProjectMember, member_user: User) -> ProjectMemberRead:
    return ProjectMemberRead(
        id=member.id,
        user_id=member.user_id,
        email=member_user.email,
        display_name=member_user.display_name,
        role=member.role,
        created_at=member.created_at,
    )


@router.get("/{project_id}/members", response_model=list[ProjectMemberRead])
def list_project_members(
    project_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[ProjectMemberRead]:
    require_project_role(db, project_id=project_id, user_id=user.id)
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.created_at)
    ).all()
    return [_member_read(member, member_user) for member, member_user in rows]


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberRead,
    status_code=status.HTTP_201_CREATED,
)
def add_project_member(
    project_id: uuid.UUID,
    payload: ProjectMemberCreate,
    db: DbSession,
    user: CurrentUser,
) -> ProjectMemberRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin"}
    )
    member_user = db.scalar(select(User).where(User.email == payload.email))
    if member_user is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ยังไม่พบบัญชีอีเมลนี้ ให้เพื่อนสมัครสมาชิกก่อนแล้วจึงเพิ่มเข้าโครงการ",
        )
    existing = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == member_user.id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ผู้ใช้นี้เป็นสมาชิกโครงการอยู่แล้ว",
        )
    member = ProjectMember(
        project_id=project_id, user_id=member_user.id, role=payload.role
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return _member_read(member, member_user)


@router.patch("/{project_id}/members/{member_id}", response_model=ProjectMemberRead)
def update_project_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: ProjectMemberUpdate,
    db: DbSession,
    user: CurrentUser,
) -> ProjectMemberRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin"}
    )
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบสมาชิกโครงการ")
    if member.role == "admin" and payload.role != "admin":
        admin_count = db.scalar(
            select(func.count(ProjectMember.id)).where(
                ProjectMember.project_id == project_id,
                ProjectMember.role == "admin",
            )
        )
        if (admin_count or 0) <= 1:
            raise HTTPException(
                status_code=409, detail="โครงการต้องมีผู้ดูแลอย่างน้อย 1 คน"
            )
    member.role = payload.role
    db.commit()
    db.refresh(member)
    member_user = db.get(User, member.user_id)
    if member_user is None:  # pragma: no cover - protected by foreign key
        raise HTTPException(status_code=404, detail="ไม่พบบัญชีผู้ใช้")
    return _member_read(member, member_user)


@router.delete("/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> None:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin"}
    )
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบสมาชิกโครงการ")
    if member.user_id == user.id:
        raise HTTPException(
            status_code=409, detail="ไม่สามารถนำบัญชีของตนเองออกจากโครงการ"
        )
    db.delete(member)
    db.commit()
