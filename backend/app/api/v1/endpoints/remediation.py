"""Remediation & Approval REST API endpoints (/api/v1/findings/{id}/proposals & /api/v1/remediation)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.dependencies.auth import get_current_user
from backend.app.application.services.remediation_service import RemediationService
from backend.app.core.exceptions import EntityNotFoundError
from backend.app.infrastructure.database.session import get_db_session
from backend.app.models.entities import (
    Approval,
    Patch,
    RegressionRun,
    RemediationProposal,
    User,
)
from backend.app.schemas.api_schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    PatchResponse,
    ProposalCreateRequest,
    RegressionRunResponse,
    RemediationProposalResponse,
)

router = APIRouter(tags=["Remediation & Approvals"])


async def _build_proposal_response(
    session: AsyncSession, proposal: RemediationProposal
) -> RemediationProposalResponse:
    patches = list(
        (
            await session.execute(
                select(Patch)
                .where(Patch.proposal_id == proposal.id)
                .order_by(Patch.created_at.desc())
            )
        ).scalars()
    )
    approvals = list(
        (
            await session.execute(
                select(Approval)
                .where(Approval.proposal_id == proposal.id)
                .order_by(Approval.decided_at.desc())
            )
        ).scalars()
    )
    patch_ids = [p.id for p in patches]
    regressions: list[RegressionRun] = []
    if patch_ids:
        regressions = list(
            (
                await session.execute(
                    select(RegressionRun)
                    .where(RegressionRun.patch_id.in_(patch_ids))
                    .order_by(RegressionRun.verified_at.desc())
                )
            ).scalars()
        )

    return RemediationProposalResponse(
        id=proposal.id,
        finding_id=proposal.finding_id,
        session_id=proposal.session_id,
        status=proposal.status,
        root_cause_analysis=proposal.root_cause_analysis,
        explanation=proposal.explanation,
        affected_files=proposal.affected_files,
        expected_behavior=proposal.expected_behavior,
        potential_impact=proposal.potential_impact,
        safety_check_results=proposal.safety_check_results,
        test_plan=proposal.test_plan,
        rollback_procedure=proposal.rollback_procedure,
        active_patch_checksum=proposal.active_patch_checksum,
        version_id=proposal.version_id,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
        patches=[PatchResponse.model_validate(p) for p in patches],
        approvals=[ApprovalResponse.model_validate(a) for a in approvals],
        regression_runs=[RegressionRunResponse.model_validate(r) for r in regressions],
    )


@router.post(
    "/findings/{finding_id}/proposals",
    response_model=RemediationProposalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_remediation_proposal(
    finding_id: UUID,
    payload: ProposalCreateRequest | None = None,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RemediationProposalResponse:
    service = RemediationService()
    override = payload.proposed_code_override if payload else None
    proposal = await service.create_proposal(
        db=session,
        finding_id=finding_id,
        proposed_code_override=override,
    )
    return await _build_proposal_response(session, proposal)


@router.get("/remediation", response_model=list[RemediationProposalResponse])
async def list_remediation_proposals(
    session_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[RemediationProposalResponse]:
    stmt = select(RemediationProposal)
    if session_id:
        stmt = stmt.where(RemediationProposal.session_id == session_id)
    if status_filter:
        stmt = stmt.where(RemediationProposal.status == status_filter.upper())
    stmt = stmt.order_by(RemediationProposal.created_at.desc()).offset(skip).limit(limit)
    proposals = list((await session.execute(stmt)).scalars().all())
    return [await _build_proposal_response(session, p) for p in proposals]


@router.get("/remediation/{proposal_id}", response_model=RemediationProposalResponse)
async def get_remediation_proposal(
    proposal_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RemediationProposalResponse:
    proposal = await session.get(RemediationProposal, proposal_id)
    if proposal is None:
        raise EntityNotFoundError("RemediationProposal", proposal_id)
    return await _build_proposal_response(session, proposal)


@router.post("/remediation/{proposal_id}/approve", response_model=RemediationProposalResponse)
async def approve_remediation_proposal(
    proposal_id: UUID,
    payload: ApprovalDecisionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RemediationProposalResponse:
    service = RemediationService()
    proposal = await service.approve_proposal(
        db=session,
        proposal_id=proposal_id,
        patch_checksum=payload.patch_checksum,
        reviewer_id=user.id,
        reviewer_name=payload.reviewer_name or user.full_name,
        comments=payload.comments,
    )
    return await _build_proposal_response(session, proposal)


@router.post("/remediation/{proposal_id}/reject", response_model=RemediationProposalResponse)
async def reject_remediation_proposal(
    proposal_id: UUID,
    payload: ApprovalDecisionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RemediationProposalResponse:
    service = RemediationService()
    proposal = await service.reject_proposal(
        db=session,
        proposal_id=proposal_id,
        patch_checksum=payload.patch_checksum,
        reviewer_id=user.id,
        reviewer_name=payload.reviewer_name or user.full_name,
        comments=payload.comments,
    )
    return await _build_proposal_response(session, proposal)


@router.post("/remediation/{proposal_id}/apply", response_model=RemediationProposalResponse)
async def apply_remediation_proposal(
    proposal_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RemediationProposalResponse:
    service = RemediationService()
    proposal = await service.apply_approved_patch(
        db=session,
        proposal_id=proposal_id,
    )
    return await _build_proposal_response(session, proposal)
