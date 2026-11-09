"""Main FastAPI Application Entrypoint for the Autonomous QC & Project Audit Intelligence Platform."""

import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import backend.app.models.entities  # noqa: F401
from backend.app.api.dependencies.auth import ensure_default_admin
from backend.app.api.v1.router import api_v1_router
from backend.app.core.config import get_settings
from backend.app.core.exceptions import register_exception_handlers
from backend.app.core.logging import logger
from backend.app.infrastructure.database.session import AsyncSessionLocal, Base, async_engine

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Initializing Autonomous QC & Project Audit Intelligence Platform...")
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSessionLocal() as session:
            await ensure_default_admin(session)
    except Exception as exc:
        logger.warning(f"Database admin bootstrap deferred: {exc}")
    yield
    logger.info("Shutting down QC Intelligence Platform.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Production-grade Autonomous QC & Project Audit Intelligence Platform "
            "with deterministic execution, evidence-backed findings, and checksum-bound human approval."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_audit_logging_middleware(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
        return response

    register_exception_handlers(app)
    app.include_router(api_v1_router, prefix=settings.API_V1_STR)

    def _find_frontend_dist() -> Path | None:
        candidates: list[Path] = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "frontend" / "dist")
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "frontend" / "dist")
            candidates.append(exe_dir.parent / "frontend" / "dist")
        candidates.extend(
            [
                Path(__file__).resolve().parents[2] / "frontend" / "dist",
                Path.cwd() / "frontend" / "dist",
            ]
        )
        return next((p for p in candidates if (p / "index.html").exists()), None)

    initial_dist = _find_frontend_dist()
    if initial_dist and (initial_dist / "assets").exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(initial_dist / "assets")),
            name="frontend_assets",
        )

    @app.get("/")
    async def root(request: Request):
        dist_dir = _find_frontend_dist()
        accept = request.headers.get("accept", "")
        if dist_dir and accept.strip().lower() != "application/json":
            return FileResponse(str(dist_dir / "index.html"))
        return JSONResponse(
            {
                "service": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "docs": "/docs",
                "health": f"{settings.API_V1_STR}/system/health",
                "ui": "bundled" if dist_dir else "dev_server",
            }
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path in {"docs", "redoc", "openapi.json"}:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        dist_dir = _find_frontend_dist()
        if dist_dir:
            candidate_file = (dist_dir / full_path).resolve()
            if str(candidate_file).startswith(str(dist_dir.resolve())) and candidate_file.is_file():
                return FileResponse(str(candidate_file))
            return FileResponse(str(dist_dir / "index.html"))
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return app


app = create_app()
