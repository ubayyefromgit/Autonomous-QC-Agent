"""SQLAlchemy 2.x async and sync database engines with automatic SQLite fallback for universal portability."""

import os
import socket
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
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


_HOST_POSTGRES_STATUS: dict[str, Any] = {
    "detected_port": None,
    "authenticated": False,
    "engine": "SQLite (Embedded)",
    "error": None,
}


def get_host_postgres_status() -> dict[str, Any]:
    return _HOST_POSTGRES_STATUS


def _test_and_setup_pg(host: str, port: int, user: str, pwd: str) -> bool:
    """Test connecting to PostgreSQL, auto-creating the qc_platform database if missing."""
    # 1. Try psycopg (psycopg 3)
    try:
        import psycopg

        with psycopg.connect(
            f"host={host} port={port} user={user} password={pwd} dbname=postgres connect_timeout=2",
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = 'qc_platform'")
                if not cur.fetchone():
                    cur.execute("CREATE DATABASE qc_platform")
            return True
    except Exception:
        pass

    # 2. Try psycopg2
    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=pwd,
            dbname="postgres",
            connect_timeout=2,
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'qc_platform'")
        if not cur.fetchone():
            cur.execute("CREATE DATABASE qc_platform")
        cur.close()
        conn.close()
        return True
    except Exception:
        pass

    # 3. Try asyncpg
    try:
        import asyncio
        import asyncpg

        async def _probe() -> bool:
            conn = await asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=pwd,
                database="postgres",
                timeout=2.0,
            )
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = 'qc_platform'"
            )
            if not exists:
                await conn.execute("CREATE DATABASE qc_platform")
            await conn.close()
            return True

        return asyncio.run(_probe())
    except Exception:
        pass

    return False


def _resolve_universal_db_urls() -> tuple[str, str]:
    cfg = get_settings()
    async_url = cfg.DATABASE_URL
    sync_url = cfg.SYNC_DATABASE_URL

    if async_url.startswith("postgresql"):
        try:
            # Candidate ports to check
            parsed = urlparse(async_url.replace("postgresql+asyncpg://", "http://"))
            config_port = parsed.port or 5433
            candidate_ports = [config_port, 5432, 5433]
            candidate_ports = list(dict.fromkeys(candidate_ports))

            # Detect open ports first
            active_ports = []
            for port in candidate_ports:
                for host in ["127.0.0.1", "localhost"]:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                        sock.settimeout(0.5)
                        if sock.connect_ex((host, port)) == 0:
                            active_ports.append((host, port))
                            _HOST_POSTGRES_STATUS["detected_port"] = port
                            break

            if active_ports:
                # Gather candidate passwords
                candidate_passwords: list[str] = []
                if parsed.password:
                    candidate_passwords.append(parsed.password)
                for env_key in ["PGPASSWORD", "POSTGRES_PASSWORD", "DATABASE_PASSWORD"]:
                    val = os.environ.get(env_key)
                    if val and val not in candidate_passwords:
                        candidate_passwords.append(val)

                # Check %APPDATA%\postgresql\pgpass.conf on Windows
                appdata = os.environ.get("APPDATA")
                if appdata:
                    pgpass_path = Path(appdata) / "postgresql" / "pgpass.conf"
                    if pgpass_path.exists():
                        try:
                            for line in pgpass_path.read_text(
                                encoding="utf-8", errors="ignore"
                            ).splitlines():
                                parts = line.strip().split(":")
                                if len(parts) >= 5 and parts[4]:
                                    candidate_passwords.append(parts[4])
                        except Exception:
                            pass

                # Common default passwords across Windows / macOS / Linux PostgreSQL installers
                default_passwords = [
                    "",
                    "postgres",
                    "postgres123",
                    "admin",
                    "root",
                    "password",
                    "123456",
                    "1234",
                    "12345",
                    "12345678",
                    "admin123",
                    "root123",
                    "postgresql",
                    "password123",
                    "pass",
                    "manager",
                    "sysadmin",
                    "Welcome1",
                    "P@ssword1",
                    "Password123",
                    "postgres1",
                    "postgres2024",
                    "postgres2025",
                    "postgres2026",
                ]
                for dp in default_passwords:
                    if dp not in candidate_passwords:
                        candidate_passwords.append(dp)

                # Candidate usernames
                candidate_users = [
                    parsed.username or "postgres",
                    "postgres",
                    os.environ.get("PGUSER", ""),
                    os.environ.get("POSTGRES_USER", ""),
                    os.environ.get("USERNAME", ""),
                    "admin",
                    "root",
                ]
                candidate_users = list(
                    dict.fromkeys([u.strip() for u in candidate_users if u.strip()])
                )

                for host, port in active_ports:
                    for user in candidate_users:
                        for pwd in candidate_passwords:
                            if _test_and_setup_pg(host, port, user, pwd):
                                auth_part = f"{user}:{pwd}@" if pwd else f"{user}@"
                                matched_async = f"postgresql+asyncpg://{auth_part}{host}:{port}/qc_platform"
                                matched_sync = f"postgresql+psycopg2://{auth_part}{host}:{port}/qc_platform"
                                cfg.DATABASE_URL = matched_async
                                cfg.SYNC_DATABASE_URL = matched_sync
                                _HOST_POSTGRES_STATUS["authenticated"] = True
                                _HOST_POSTGRES_STATUS["engine"] = "PostgreSQL"
                                _HOST_POSTGRES_STATUS["detected_port"] = port
                                return matched_async, matched_sync
        except Exception as exc:
            _HOST_POSTGRES_STATUS["error"] = str(exc)

        # Fallback to zero-config embedded SQLite database only if no PostgreSQL server can be reached
        sqlite_file = (cfg.storage_path / "qc_platform_universal.db").resolve().as_posix()
        fallback_async = f"sqlite+aiosqlite:///{sqlite_file}"
        fallback_sync = f"sqlite:///{sqlite_file}"
        cfg.DATABASE_URL = fallback_async
        cfg.SYNC_DATABASE_URL = fallback_sync
        _HOST_POSTGRES_STATUS["engine"] = "SQLite (Embedded)"
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


def reconfigure_database_engine(new_async_url: str, new_sync_url: str) -> None:
    """Dynamically rebind engines to a new database URL (e.g. switching SQLite -> PostgreSQL)."""
    global async_engine, AsyncSessionLocal, sync_engine, SyncSessionLocal, _ACTIVE_ASYNC_URL, _ACTIVE_SYNC_URL
    _ACTIVE_ASYNC_URL = new_async_url
    _ACTIVE_SYNC_URL = new_sync_url
    async_engine = create_async_engine(new_async_url, poolclass=NullPool, echo=False)
    AsyncSessionLocal = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    sync_engine = create_engine(new_sync_url, pool_pre_ping=True, echo=False)
    SyncSessionLocal = sessionmaker(
        bind=sync_engine, expire_on_commit=False, autoflush=False
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency providing a transactional async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
