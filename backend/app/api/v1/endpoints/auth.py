"""Authentication endpoints (/api/v1/auth)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.dependencies.auth import ensure_default_admin, get_current_user
from backend.app.core.exceptions import QCPlatformError
from backend.app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from backend.app.infrastructure.database.session import get_db_session
from backend.app.models.entities import User
from backend.app.schemas.api_schemas import (
    LoginRequest,
    TokenResponse,
    UserCreateRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    existing = await session.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise QCPlatformError(
            message=f"User with email '{payload.email}' already exists.",
            status_code=status.HTTP_409_CONFLICT,
            code="USER_ALREADY_EXISTS",
        )
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    token = create_access_token(subject=str(user.id), role=user.role)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    await ensure_default_admin(session)
    stmt = select(User).where(User.email == payload.email, User.is_active.is_(True))
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise QCPlatformError(
            message="Invalid email or password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_CREDENTIALS",
        )
    token = create_access_token(subject=str(user.id), role=user.role)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)
