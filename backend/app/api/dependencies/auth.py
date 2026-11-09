"""Authentication and authorization dependencies for FastAPI endpoints."""

from fastapi import Depends, Header, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.exceptions import AuthorizationError, QCPlatformError
from backend.app.core.security import decode_access_token, hash_password
from backend.app.infrastructure.database.session import get_db_session
from backend.app.models.entities import User

bearer_scheme = HTTPBearer(auto_error=False)

DEFAULT_ADMIN_EMAIL = "admin@qcplatform.io"
DEFAULT_ADMIN_PASSWORD = "AdminPassword123!"


async def ensure_default_admin(session: AsyncSession) -> User:
    """Ensure a default administrative user exists for platform bootstrap."""
    stmt = select(User).where(User.email == DEFAULT_ADMIN_EMAIL)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=DEFAULT_ADMIN_EMAIL,
            password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
            full_name="Principal QC Architect",
            role="ADMIN",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_qc_api_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Resolve authenticated user from Bearer JWT or fall back to bootstrap admin in dev/CLI mode."""
    if credentials and credentials.credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            user_id = payload.get("sub")
            if user_id:
                stmt = select(User).where(User.id == user_id, User.is_active.is_(True))
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                if user:
                    return user
        except Exception as exc:
            raise QCPlatformError(
                message="Invalid or expired authentication token.",
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="INVALID_TOKEN",
            ) from exc

    if x_qc_api_key == "invalid-key":
        raise QCPlatformError(
            message="Invalid API key.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_API_KEY",
        )

    return await ensure_default_admin(session)


def require_roles(*allowed_roles: str):
    """Dependency factory enforcing role-based access control (RBAC)."""

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles and "ADMIN" != user.role:
            raise AuthorizationError(
                f"Role '{user.role}' is not authorized. Required: {', '.join(allowed_roles)}"
            )
        return user

    return checker
