"""Master API v1 router aggregating all domain endpoints."""

from fastapi import APIRouter

from backend.app.api.v1.endpoints import (
    audits,
    auth,
    findings,
    projects,
    remediation,
    reports,
    system,
)

api_v1_router = APIRouter()
api_v1_router.include_router(auth.router)
api_v1_router.include_router(projects.router)
api_v1_router.include_router(audits.router)
api_v1_router.include_router(findings.router)
api_v1_router.include_router(remediation.router)
api_v1_router.include_router(reports.router)
api_v1_router.include_router(system.router)
