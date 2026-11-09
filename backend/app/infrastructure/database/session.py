"""SQLAlchemy 2.x async and sync database engines with automatic SQLite fallback for universal portability."""

import socket
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from backend.app.core.config import get_settings


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy 2.x models."""


def _resolve_universal_db_urls() -> tuple[str, str]:
    cfg = get_settings()
    async_url = cfg.DATABASE_URL
    sync_url = cfg.SYNC_DATABASE_URL

    if async_url.startswith("postgresql"):
        try:
            import asyncpg  # noqa: F401

            parsed = urlparse(async_url.replace("postgresql+asyncpg://", "http://"))
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 5432
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.6)
                if sock.connect_ex((host, port)) == 0:
                    return async_url, sync_url
        except Exception:
            pass

        # Fallback to zero-config embedded SQLite database when PostgreSQL is not running on host
        sqlite_file = (cfg.storage_path / "qc_platform_universal.db").resolve().as_posix()
        fallback_async = f"sqlite+aiosqlite:///{sqlite_file}"
        fallback_sync = f"sqlite:///{sqlite_file}"
        cfg.DATABASE_URL = fallback_async
        cfg.SYNC_DATABASE_URL = fallback_sync
        return fallback_async, fallback_sync

    return async_url, sync_url


settings = get_settings()
_ACTIVE_ASYNC_URL, _ACTIVE_SYNC_URL = _resolve_universal_db_urls()

async_engine: AsyncEngine = create_async_engine(
    _ACTIVE_ASYNC_URL,
    poolclass=NullPool,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

sync_engine = create_engine(
    _ACTIVE_SYNC_URL,
    pool_pre_ping=True,
    echo=False,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency providing a transactional async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
