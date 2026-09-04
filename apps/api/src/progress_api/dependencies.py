import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from progress_api.config import get_settings
from progress_api.db import get_db
from progress_api.models import User
from progress_api.security import decode_access_token

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")
DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="ไม่สามารถยืนยันตัวตนได้",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = uuid.UUID(decode_access_token(token))
    except (ValueError, jwt.PyJWTError):
        raise credentials_error from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

