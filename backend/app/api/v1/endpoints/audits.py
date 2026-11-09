"""Audit Sessions, Live Progress, Resumption & SSE endpoints (/api/v1/audits & /api/v1/projects/{id}/audits)."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.orchestrator.master_orchestrator import MasterAuditOrchestrator
from backend.app.api.dependencies.auth import get_current_user
from backend.app.core.exceptions import EntityNotFoundError
from backend.app.domain.entities.state_machines import AuditStateMachine
from backend.app.domain.enums.audit_enums import AuditSessionStatus
from backend.app.infrastructure.database.session import (
    AsyncSessionLocal,
    get_db_session,
)
from backend.app.models.entities import (
    AuditMetric,
    AuditSession,
    AuditTask,
    ExecutionLog,
    Project,
    TestRun,
    User,
)
from backend.app.schemas.api_schemas import (
    AuditCreateRequest,
    AuditMetricResponse,
    AuditProgressResponse,
    AuditSessionResponse,
    AuditTaskResponse,
    ExecutionLogResponse,
    TestRunResponse,
)

router = APIRouter(tags=["Audits"])


async def _run_audit_in_background(session_id: UUID, resume: bool = False) -> None:
    orchestrator = MasterAuditOrchestrator()
    async with AsyncSessionLocal() as bg_db:
        try:
            await orchestrator.execute_audit_session(
                db=bg_db, session_id=session_id, resume=resume
            )
        except Exception as exc:
            audit_session = await bg_db.get(AuditSession, session_id)
            if audit_session is not None:
                audit_session.status = AuditSessionStatus.FAILED.value
                audit_session.error_summary = str(exc)
                audit_session.completed_at = datetime.now(UTC)
                await bg_db.commit()


@router.post(
    "/projects/{project_id}/audits",
    response_model=AuditSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_and_start_audit(
    project_id: UUID,
    payload: AuditCreateRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AuditSessionResponse:
    project = await session.get(Project, project_id)
    if project is None or project.is_deleted:
        raise EntityNotFoundError("Project", project_id)

    audit_session = AuditSession(
        project_id=project.id,
        triggered_by=user.id,
        status=AuditSessionStatus.CREATED.value,
        current_phase="CREATED",
        audit_scope=payload.audit_scope.upper(),
        runner_mode=payload.runner_mode.upper(),
        release_gate="INCOMPLETE_AUDIT",
        environment_snapshot={
            "custom_instructions": (payload.custom_instructions or "").strip(),
        },
    )
    session.add(audit_session)
    await session.commit()
    await session.refresh(audit_session)

    if payload.run_immediately:
        if payload.run_synchronously:
            orchestrator = MasterAuditOrchestrator()
            audit_session = await orchestrator.execute_audit_session(
                db=session, session_id=audit_session.id, resume=False
            )
        else:
            background_tasks.add_task(
                _run_audit_in_background, audit_session.id, False
            )

    resp = AuditSessionResponse.model_validate(audit_session)
    resp.project_name = project.name
    return resp


@router.get("/audits", response_model=list[AuditSessionResponse])
async def list_audits(
    project_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditSessionResponse]:
    stmt = select(AuditSession, Project.name).join(
        Project, Project.id == AuditSession.project_id
    )
    if project_id:
        stmt = stmt.where(AuditSession.project_id == project_id)
    if status_filter:
        stmt = stmt.where(AuditSession.status == status_filter.upper())

    stmt = stmt.order_by(AuditSession.created_at.desc()).offset(skip).limit(limit)
    rows = (await session.execute(stmt)).all()
    results: list[AuditSessionResponse] = []
    for audit_obj, proj_name in rows:
        item = AuditSessionResponse.model_validate(audit_obj)
        item.project_name = proj_name
        results.append(item)
    return results


@router.get("/audits/{audit_id}", response_model=AuditSessionResponse)
async def get_audit(
    audit_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AuditSessionResponse:
    audit_session = await session.get(AuditSession, audit_id)
    if audit_session is None:
        raise EntityNotFoundError("AuditSession", audit_id)
    project = await session.get(Project, audit_session.project_id)
    resp = AuditSessionResponse.model_validate(audit_session)
    resp.project_name = project.name if project else None
    return resp


@router.post("/audits/{audit_id}/cancel", response_model=AuditSessionResponse)
async def cancel_audit(
    audit_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AuditSessionResponse:
    audit_session = await session.get(AuditSession, audit_id)
    if audit_session is None:
        raise EntityNotFoundError("AuditSession", audit_id)

    current = AuditSessionStatus(audit_session.status)
    AuditStateMachine.validate_transition(current, AuditSessionStatus.CANCELLED)
    audit_session.status = AuditSessionStatus.CANCELLED.value
    audit_session.current_phase = "CANCELLED"
    audit_session.completed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(audit_session)
    return AuditSessionResponse.model_validate(audit_session)


@router.post("/audits/{audit_id}/resume", response_model=AuditSessionResponse)
async def resume_interrupted_audit(
    audit_id: UUID,
    run_synchronously: bool = Query(default=True),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AuditSessionResponse:
    audit_session = await session.get(AuditSession, audit_id)
    if audit_session is None:
        raise EntityNotFoundError("AuditSession", audit_id)

    if run_synchronously:
        orchestrator = MasterAuditOrchestrator()
        audit_session = await orchestrator.execute_audit_session(
            db=session, session_id=audit_id, resume=True
        )
    else:
        background_tasks.add_task(_run_audit_in_background, audit_id, True)

    return AuditSessionResponse.model_validate(audit_session)


@router.get("/audits/{audit_id}/progress", response_model=AuditProgressResponse)
async def get_audit_progress(
    audit_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AuditProgressResponse:
    audit_session = await session.get(AuditSession, audit_id)
    if audit_session is None:
        raise EntityNotFoundError("AuditSession", audit_id)

    tasks = list(
        (
            await session.execute(
                select(AuditTask)
                .where(AuditTask.session_id == audit_id)
                .order_by(AuditTask.created_at.asc())
            )
        ).scalars()
    )
    logs = list(
        (
            await session.execute(
                select(ExecutionLog)
                .where(ExecutionLog.session_id == audit_id)
                .order_by(ExecutionLog.executed_at.desc())
                .limit(30)
            )
        ).scalars()
    )

    total = len(tasks) or audit_session.total_tasks
    completed = sum(1 for t in tasks if t.status == "COMPLETED")
    failed = sum(1 for t in tasks if t.status == "FAILED")
    active_agents = [t.agent_type for t in tasks if t.status == "RUNNING"]

    # Deterministic progress strictly derived from actual completed tasks
    progress_pct = round((completed / total) * 100.0, 1) if total > 0 else (
        100.0 if audit_session.status == "COMPLETED" else 0.0
    )

    now = datetime.now(UTC)
    start_ts = audit_session.started_at or audit_session.created_at
    end_ts = audit_session.completed_at or now
    elapsed = max(0.0, round((end_ts - start_ts).total_seconds(), 2))

    return AuditProgressResponse(
        audit_id=audit_session.id,
        project_id=audit_session.project_id,
        status=audit_session.status,
        current_phase=audit_session.current_phase,
        total_tasks=total,
        completed_tasks=completed,
        failed_tasks=failed,
        progress_percent=progress_pct,
        active_agents=active_agents,
        elapsed_seconds=elapsed,
        tasks=[AuditTaskResponse.model_validate(t) for t in tasks],
        recent_logs=[ExecutionLogResponse.model_validate(lg) for lg in logs],
    )


@router.get("/audits/{audit_id}/tasks", response_model=list[AuditTaskResponse])
async def list_audit_tasks(
    audit_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditTaskResponse]:
    tasks = list(
        (
            await session.execute(
                select(AuditTask)
                .where(AuditTask.session_id == audit_id)
                .order_by(AuditTask.created_at.asc())
            )
        ).scalars()
    )
    return [AuditTaskResponse.model_validate(t) for t in tasks]


@router.get("/audits/{audit_id}/test-runs", response_model=list[TestRunResponse])
async def list_audit_test_runs(
    audit_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[TestRunResponse]:
    runs = list(
        (
            await session.execute(
                select(TestRun)
                .where(TestRun.session_id == audit_id)
                .order_by(TestRun.executed_at.asc())
            )
        ).scalars()
    )
    return [TestRunResponse.model_validate(r) for r in runs]


@router.get("/audits/{audit_id}/metrics", response_model=list[AuditMetricResponse])
async def list_audit_metrics(
    audit_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditMetricResponse]:
    metrics = list(
        (
            await session.execute(
                select(AuditMetric)
                .where(AuditMetric.session_id == audit_id)
                .order_by(AuditMetric.recorded_at.asc())
            )
        ).scalars()
    )
    return [AuditMetricResponse.model_validate(m) for m in metrics]


@router.get("/audits/{audit_id}/logs", response_model=list[ExecutionLogResponse])
async def list_audit_execution_logs(
    audit_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ExecutionLogResponse]:
    logs = list(
        (
            await session.execute(
                select(ExecutionLog)
                .where(ExecutionLog.session_id == audit_id)
                .order_by(ExecutionLog.executed_at.desc())
                .limit(100)
            )
        ).scalars()
    )
    return [ExecutionLogResponse.model_validate(lg) for lg in logs]


async def _fetch_sse_snapshot(audit_id: UUID) -> dict | None:
    async with AsyncSessionLocal() as db:
        audit_session = await db.get(AuditSession, audit_id)
        if audit_session is None:
            return None
        return {
            "audit_id": str(audit_session.id),
            "status": audit_session.status,
            "current_phase": audit_session.current_phase,
            "total_tasks": audit_session.total_tasks,
            "completed_tasks": audit_session.completed_tasks,
            "failed_tasks": audit_session.failed_tasks,
            "overall_score": audit_session.overall_score,
            "release_gate": audit_session.release_gate,
        }


@router.get("/audits/{audit_id}/stream")
async def stream_audit_progress_sse(
    audit_id: UUID,
) -> StreamingResponse:
    """Server-Sent Events (SSE) stream providing real-time task progress updates."""

    async def event_generator():
        ticks = 0
        while ticks < 30:
            ticks += 1
            payload = await _fetch_sse_snapshot(audit_id)
            if payload is None:
                yield f"data: {json.dumps({'error': 'NOT_FOUND'})}\n\n"
                break
            yield f"data: {json.dumps(payload)}\n\n"
            if payload["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
