import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from progress_api.models import ProjectMember


def require_project_role(
    db: Session,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    allowed_roles: set[str] | None = None,
) -> str:
    role = db.scalar(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if role is None or (allowed_roles is not None and role not in allowed_roles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบโครงการ")
    return role
