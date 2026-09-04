from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from progress_api.dependencies import CurrentUser, DbSession
from progress_api.models import User
from progress_api.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserRead
from progress_api.security import create_access_token, hash_password, verify_password

router = APIRouter()


def _token_response(user: User) -> TokenResponse:
    token, expires_in = create_access_token(str(user.id))
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    email = payload.email.lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="อีเมลนี้ถูกใช้งานแล้ว")

    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="บัญชีถูกระงับ")
    return _token_response(user)


@router.get("/me", response_model=UserRead)
def current_user(user: CurrentUser) -> User:
    return user

