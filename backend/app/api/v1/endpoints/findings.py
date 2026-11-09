"""Findings & Evidence REST API endpoints (/api/v1/findings & /api/v1/evidence)."""

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.dependencies.auth import get_current_user
from backend.app.core.exceptions import EntityNotFoundError
from backend.app.domain.entities.state_machines import FindingStateMachine
from backend.app.domain.enums.audit_enums import (
    FindingLifecycleStatus,
    FindingVerificationStatus,
)
from backend.app.infrastructure.database.session import get_db_session
from backend.app.models.entities import (
    Evidence,
    Finding,
    Patch,
    RegressionRun,
    RemediationProposal,
    User,
)
from backend.app.schemas.api_schemas import (
    EvidenceResponse,
    FindingResponse,
    FindingUpdateRequest,
)

router = APIRouter(tags=["Findings & Evidence"])


async def _enrich_finding(session: AsyncSession, finding: Finding) -> FindingResponse:
    ev_count = int(
        (
            await session.execute(
                select(func.count(Evidence.id)).where(Evidence.finding_id == finding.id)
            )
        ).scalar()
        or 0
    )
    resp = FindingResponse.model_validate(finding)
    resp.evidence_count = ev_count
    return resp


@router.get("/audits/{audit_id}/findings", response_model=list[FindingResponse])
async def list_audit_findings(
    audit_id: UUID,
    severity: str | None = Query(default=None),
    category: str | None = Query(default=None),
    agent_name: str | None = Query(default=None),
    verification_status: str | None = Query(default=None),
    lifecycle_status: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[FindingResponse]:
    stmt = select(Finding).where(Finding.session_id == audit_id)
    if severity:
        stmt = stmt.where(Finding.severity == severity.upper())
    if category:
        stmt = stmt.where(Finding.category == category.upper())
    if agent_name:
        stmt = stmt.where(Finding.agent_name == agent_name)
    if verification_status:
        stmt = stmt.where(Finding.verification_status == verification_status.upper())
    if lifecycle_status:
        stmt = stmt.where(Finding.lifecycle_status == lifecycle_status.upper())

    stmt = stmt.order_by(Finding.created_at.desc()).offset(skip).limit(limit)
    findings = list((await session.execute(stmt)).scalars().all())
    return [await _enrich_finding(session, f) for f in findings]


@router.get("/findings", response_model=list[FindingResponse])
async def list_all_findings(
    project_id: UUID | None = Query(default=None),
    session_id: UUID | None = Query(default=None),
    severity: str | None = Query(default=None),
    category: str | None = Query(default=None),
    agent_name: str | None = Query(default=None),
    file_path: str | None = Query(default=None),
    verification_status: str | None = Query(default=None),
    lifecycle_status: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[FindingResponse]:
    stmt = select(Finding)
    if project_id:
        stmt = stmt.where(Finding.project_id == project_id)
    if session_id:
        stmt = stmt.where(Finding.session_id == session_id)
    if severity:
        stmt = stmt.where(Finding.severity == severity.upper())
    if category:
        stmt = stmt.where(Finding.category == category.upper())
    if agent_name:
        stmt = stmt.where(Finding.agent_name == agent_name)
    if file_path:
        stmt = stmt.where(Finding.file_path.ilike(f"%{file_path}%"))
    if verification_status:
        stmt = stmt.where(Finding.verification_status == verification_status.upper())
    if lifecycle_status:
        stmt = stmt.where(Finding.lifecycle_status == lifecycle_status.upper())

    stmt = stmt.order_by(Finding.created_at.desc()).offset(skip).limit(limit)
    findings = list((await session.execute(stmt)).scalars().all())
    return [await _enrich_finding(session, f) for f in findings]


@router.get("/findings/{finding_id}", response_model=FindingResponse)
async def get_finding(
    finding_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> FindingResponse:
    finding = await session.get(Finding, finding_id)
    if finding is None:
        raise EntityNotFoundError("Finding", finding_id)
    return await _enrich_finding(session, finding)


@router.patch("/findings/{finding_id}", response_model=FindingResponse)
async def update_finding(
    finding_id: UUID,
    payload: FindingUpdateRequest,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> FindingResponse:
    finding = await session.get(Finding, finding_id)
    if finding is None:
        raise EntityNotFoundError("Finding", finding_id)

    ev_count = int(
        (
            await session.execute(
                select(func.count(Evidence.id)).where(Evidence.finding_id == finding.id)
            )
        ).scalar()
        or 0
    )

    if payload.verification_status is not None:
        target_ver = FindingVerificationStatus(payload.verification_status.upper())
        FindingStateMachine.validate_verification_promotion(target_ver, ev_count)
        finding.verification_status = target_ver.value

    if payload.lifecycle_status is not None:
        target_life = FindingLifecycleStatus(payload.lifecycle_status.upper())
        if target_life == FindingLifecycleStatus.RESOLVED:
            # Verify whether a passing regression run exists for this finding
            reg_stmt = (
                select(func.count(RegressionRun.id))
                .join(Patch, Patch.id == RegressionRun.patch_id)
                .join(RemediationProposal, RemediationProposal.id == Patch.proposal_id)
                .where(
                    RemediationProposal.finding_id == finding.id,
                    RegressionRun.issue_resolved.is_(True),
                )
            )
            passed_reg = int((await session.execute(reg_stmt)).scalar() or 0) > 0
            FindingStateMachine.validate_resolution(target_life, passed_reg)
        finding.lifecycle_status = target_life.value

    if payload.recommended_fix is not None:
        finding.recommended_fix = payload.recommended_fix
    if payload.root_cause is not None:
        finding.root_cause = payload.root_cause

    await session.commit()
    await session.refresh(finding)
    return await _enrich_finding(session, finding)


@router.get("/findings/{finding_id}/evidence", response_model=list[EvidenceResponse])
async def list_finding_evidence(
    finding_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[EvidenceResponse]:
    finding = await session.get(Finding, finding_id)
    if finding is None:
        raise EntityNotFoundError("Finding", finding_id)
    stmt = (
        select(Evidence)
        .where(Evidence.finding_id == finding_id)
        .order_by(Evidence.created_at.asc())
    )
    items = list((await session.execute(stmt)).scalars().all())
    return [EvidenceResponse.model_validate(item) for item in items]


@router.get("/evidence", response_model=list[EvidenceResponse])
async def list_all_evidence(
    session_id: UUID | None = Query(default=None),
    evidence_type: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[EvidenceResponse]:
    stmt = select(Evidence)
    if session_id:
        stmt = stmt.where(Evidence.session_id == session_id)
    if evidence_type:
        stmt = stmt.where(Evidence.evidence_type == evidence_type.upper())
    stmt = stmt.order_by(Evidence.created_at.desc()).offset(skip).limit(limit)
    items = list((await session.execute(stmt)).scalars().all())
    return [EvidenceResponse.model_validate(item) for item in items]


@router.get("/evidence/{evidence_id}/artifact")
async def download_evidence_artifact(
    evidence_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    ev = await session.get(Evidence, evidence_id)
    if ev is None:
        raise EntityNotFoundError("Evidence", evidence_id)
    p = Path(ev.storage_uri)
    if p.exists() and p.is_file():
        return FileResponse(str(p), filename=p.name)
    return PlainTextResponse(ev.content_excerpt or "Artifact content unavailable.")
