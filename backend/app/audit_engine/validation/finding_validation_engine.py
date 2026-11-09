"""FindingValidationEngine — Evidence enforcement, fingerprinting, deduplication & history tracking."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit_engine.evidence.evidence_service import EvidenceService
from backend.app.core.security import compute_finding_fingerprint
from backend.app.domain.enums.audit_enums import (
    FindingLifecycleStatus,
    FindingVerificationStatus,
)
from backend.app.domain.interfaces.contracts import FindingCreateDTO
from backend.app.models.entities import Evidence, Finding


class FindingValidationEngine:
    """Validates findings, enforces Evidence-First guarantees, deduplicates, and tracks history."""

    def __init__(self, evidence_service: EvidenceService | None = None) -> None:
        self.evidence_service = evidence_service or EvidenceService()

    async def ingest_finding(
        self,
        db: AsyncSession,
        project_id: UUID,
        session_id: UUID,
        task_id: UUID | None,
        dto: FindingCreateDTO,
    ) -> Finding:
        fingerprint = compute_finding_fingerprint(
            project_id=str(project_id),
            category=str(dto.category),
            file_path=dto.file_path,
            title=dto.title,
            line_start=dto.line_start,
        )

        # 1. Check if finding with same fingerprint already exists in this audit session
        existing_in_session_stmt = select(Finding).where(
            Finding.session_id == session_id,
            Finding.fingerprint == fingerprint,
        )
        existing_in_session = (await db.execute(existing_in_session_stmt)).scalar_one_or_none()

        has_evidence = len(dto.evidence_items) > 0 or len(dto.evidence_ids) > 0

        if existing_in_session is not None:
            for ev_dto in dto.evidence_items:
                await self.evidence_service.store_evidence(
                    db=db,
                    session_id=session_id,
                    task_id=task_id,
                    finding_id=existing_in_session.id,
                    evidence_type=str(ev_dto.evidence_type),
                    source_tool=ev_dto.source_tool,
                    content_bytes=ev_dto.content_bytes,
                    content_text=ev_dto.content_text,
                    content_excerpt=ev_dto.content_excerpt,
                    metadata_json=ev_dto.metadata_json,
                    filename_hint=ev_dto.filename_hint,
                )
            if has_evidence and existing_in_session.verification_status in {
                FindingVerificationStatus.UNVERIFIED.value,
                FindingVerificationStatus.SUSPECTED.value,
            }:
                if dto.verification_status in {
                    FindingVerificationStatus.CONFIRMED,
                    FindingVerificationStatus.REPRODUCED,
                }:
                    existing_in_session.verification_status = str(dto.verification_status)
            await db.flush()
            return existing_in_session

        # 2. Enforce Evidence-First policy: never allow CONFIRMED or REPRODUCED without evidence
        verification_status = str(dto.verification_status)
        if verification_status in {
            FindingVerificationStatus.CONFIRMED.value,
            FindingVerificationStatus.REPRODUCED.value,
        } and not has_evidence:
            verification_status = FindingVerificationStatus.SUSPECTED.value

        # 3. Check historical findings across prior sessions for this project
        history_stmt = (
            select(Finding)
            .where(
                Finding.project_id == project_id,
                Finding.fingerprint == fingerprint,
                Finding.session_id != session_id,
            )
            .order_by(Finding.created_at.desc())
            .limit(1)
        )
        historical = (await db.execute(history_stmt)).scalar_one_or_none()

        lifecycle_status = FindingLifecycleStatus.NEW.value
        occurrence_count = 1
        first_seen_session_id = session_id

        if historical is not None:
            occurrence_count = historical.occurrence_count + 1
            first_seen_session_id = historical.first_seen_session_id or historical.session_id
            if historical.lifecycle_status == FindingLifecycleStatus.RESOLVED.value:
                lifecycle_status = FindingLifecycleStatus.REOPENED.value
            elif historical.lifecycle_status == FindingLifecycleStatus.ACCEPTED_RISK.value:
                lifecycle_status = FindingLifecycleStatus.ACCEPTED_RISK.value
            else:
                lifecycle_status = FindingLifecycleStatus.RECURRING.value

        finding = Finding(
            project_id=project_id,
            session_id=session_id,
            fingerprint=fingerprint,
            category=str(dto.category),
            severity=str(dto.severity),
            title=dto.title,
            description=dto.description,
            file_path=dto.file_path,
            line_start=dto.line_start,
            line_end=dto.line_end,
            agent_name=dto.agent_name,
            reproduction_steps=dto.reproduction_steps,
            expected_behavior=dto.expected_behavior,
            actual_behavior=dto.actual_behavior,
            root_cause=dto.root_cause,
            impact=dto.impact,
            recommended_fix=dto.recommended_fix,
            confidence=dto.confidence,
            verification_status=verification_status,
            lifecycle_status=lifecycle_status,
            occurrence_count=occurrence_count,
            first_seen_session_id=first_seen_session_id,
        )
        db.add(finding)
        await db.flush()

        # 4. Persist attached evidence records
        for ev_dto in dto.evidence_items:
            await self.evidence_service.store_evidence(
                db=db,
                session_id=session_id,
                task_id=task_id,
                finding_id=finding.id,
                evidence_type=str(ev_dto.evidence_type),
                source_tool=ev_dto.source_tool,
                content_bytes=ev_dto.content_bytes,
                content_text=ev_dto.content_text,
                content_excerpt=ev_dto.content_excerpt,
                metadata_json=ev_dto.metadata_json,
                filename_hint=ev_dto.filename_hint,
            )

        for ev_id in dto.evidence_ids:
            ev_obj = await db.get(Evidence, ev_id)
            if ev_obj is not None and ev_obj.finding_id is None:
                ev_obj.finding_id = finding.id

        await db.flush()
        return finding
