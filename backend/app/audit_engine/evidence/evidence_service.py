"""EvidenceService — Content-addressable SHA-256 artifact storage & secret redaction."""

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import redact_secrets
from backend.app.core.security import compute_sha256_bytes
from backend.app.models.entities import Evidence


class EvidenceService:
    """Persists verifiable evidence artifacts outside PostgreSQL and tracks metadata + checksums."""

    def __init__(self, storage_root: Path | None = None) -> None:
        settings = get_settings()
        self.storage_root = (storage_root or settings.storage_path) / "evidence"
        self.storage_root.mkdir(parents=True, exist_ok=True)

    async def store_evidence(
        self,
        db: AsyncSession,
        session_id: UUID,
        evidence_type: str,
        source_tool: str,
        content_bytes: bytes | None = None,
        content_text: str | None = None,
        content_excerpt: str | None = None,
        task_id: UUID | None = None,
        finding_id: UUID | None = None,
        metadata_json: dict[str, Any] | None = None,
        filename_hint: str = "artifact.txt",
    ) -> Evidence:
        if content_bytes is None:
            safe_text = redact_secrets(content_text or content_excerpt or "")
            raw_bytes = safe_text.encode("utf-8")
        else:
            raw_bytes = content_bytes

        checksum = compute_sha256_bytes(raw_bytes)
        ext = Path(filename_hint).suffix or ".txt"
        session_dir = self.storage_root / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = session_dir / f"{checksum[:24]}{ext}"
        artifact_path.write_bytes(raw_bytes)

        excerpt = content_excerpt
        if excerpt is None and content_text is not None:
            excerpt = redact_secrets(content_text[:2000])
        elif excerpt is not None:
            excerpt = redact_secrets(excerpt[:2000])

        evidence = Evidence(
            session_id=session_id,
            task_id=task_id,
            finding_id=finding_id,
            evidence_type=evidence_type,
            storage_uri=str(artifact_path),
            sha256_checksum=checksum,
            source_tool=source_tool,
            content_excerpt=excerpt,
            metadata_json=metadata_json or {},
        )
        db.add(evidence)
        await db.flush()
        return evidence

    async def get_evidence_for_finding(
        self, db: AsyncSession, finding_id: UUID
    ) -> list[Evidence]:
        stmt = (
            select(Evidence)
            .where(Evidence.finding_id == finding_id)
            .order_by(Evidence.created_at.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
