"""Report Generation & Download REST API endpoints (/api/v1/audits/{id}/reports & /api/v1/reports)."""

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.dependencies.auth import get_current_user
from backend.app.audit_engine.reporting.report_service import ReportService
from backend.app.core.exceptions import EntityNotFoundError
from backend.app.infrastructure.database.session import get_db_session
from backend.app.models.entities import AuditSession, Report, User
from backend.app.schemas.api_schemas import ReportGenerateRequest, ReportResponse

router = APIRouter(tags=["Reports"])


@router.post(
    "/audits/{audit_id}/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_audit_report(
    audit_id: UUID,
    payload: ReportGenerateRequest | None = None,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReportResponse:
    audit_session = await session.get(AuditSession, audit_id)
    if audit_session is None:
        raise EntityNotFoundError("AuditSession", audit_id)

    fmt = payload.report_format.upper() if payload else "HTML"
    service = ReportService()
    report = await service.generate_report(
        db=session, session_id=audit_id, report_format=fmt
    )
    await session.commit()
    await session.refresh(report)
    return ReportResponse.model_validate(report)


@router.get("/audits/{audit_id}/reports", response_model=list[ReportResponse])
async def list_audit_reports(
    audit_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ReportResponse]:
    stmt = (
        select(Report)
        .where(Report.session_id == audit_id)
        .order_by(Report.generated_at.desc())
    )
    reports = list((await session.execute(stmt)).scalars().all())
    return [ReportResponse.model_validate(r) for r in reports]


@router.get("/reports", response_model=list[ReportResponse])
async def list_all_reports(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ReportResponse]:
    stmt = select(Report).order_by(Report.generated_at.desc()).limit(100)
    reports = list((await session.execute(stmt)).scalars().all())
    return [ReportResponse.model_validate(r) for r in reports]


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    report = await session.get(Report, report_id)
    if report is None:
        raise EntityNotFoundError("Report", report_id)
    p = Path(report.storage_uri)
    if not p.exists():
        raise EntityNotFoundError("ReportFile", report.storage_uri)
    if report.report_format.upper() == "HTML":
        return HTMLResponse(p.read_text(encoding="utf-8", errors="replace"))
    return FileResponse(str(p), media_type="application/pdf", filename=p.name)
