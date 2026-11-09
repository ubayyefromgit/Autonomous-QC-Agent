"""Authentication, JWT token management, password hashing, and cryptographic integrity."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from backend.app.core.config import get_settings


def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(
    subject: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def compute_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_finding_fingerprint(
    project_id: str,
    category: str,
    file_path: str | None,
    title: str,
    line_start: int | None = None,
) -> str:
    """Compute a deterministic fingerprint to deduplicate findings across agents and sessions."""
    normalized_path = (file_path or "global").replace("\\", "/").strip().lower()
    normalized_title = title.strip().lower()
    line_bucket = (line_start // 5) if line_start is not None else 0
    raw = f"{project_id}|{category}|{normalized_path}|{normalized_title}|{line_bucket}"
    return compute_sha256_text(raw)[:32]


def compute_patch_checksum(target_file_path: str, unified_diff: str) -> str:
    """Compute immutable SHA-256 checksum binding an approval to the exact proposed diff."""
    normalized_path = target_file_path.replace("\\", "/").strip()
    normalized_diff = unified_diff.replace("\r\n", "\n").strip()
    return compute_sha256_text(f"{normalized_path}\n---\n{normalized_diff}")
