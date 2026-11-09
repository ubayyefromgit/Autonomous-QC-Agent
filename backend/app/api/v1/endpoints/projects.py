"""Projects & Repository Discovery REST API endpoints (/api/v1/projects)."""

import asyncio
import io
import json
import re
import shutil
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.api.dependencies.auth import get_current_user
from backend.app.audit_engine.discovery.repository_intelligence_engine import (
    RepositoryIntelligenceEngine,
)
from backend.app.core.config import get_settings
from backend.app.core.exceptions import EntityNotFoundError, QCPlatformError
from backend.app.infrastructure.database.session import get_db_session
from backend.app.models.entities import (
    AuditSession,
    Finding,
    Project,
    ProjectConfiguration,
    ProjectMember,
    RepositoryFile,
    User,
)
from backend.app.schemas.api_schemas import (
    ProjectConfigUpdateRequest,
    ProjectConfigurationResponse,
    ProjectCreateRequest,
    ProjectResponse,
    RepositoryFileResponse,
)

router = APIRouter(prefix="/projects", tags=["Projects & Discovery"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "project"


async def _enrich_project_response(
    session: AsyncSession, project: Project
) -> ProjectResponse:
    audits_count = int(
        (
            await session.execute(
                select(func.count(AuditSession.id)).where(
                    AuditSession.project_id == project.id
                )
            )
        ).scalar()
        or 0
    )
    latest_audit = (
        await session.execute(
            select(AuditSession)
            .where(AuditSession.project_id == project.id)
            .order_by(AuditSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    unresolved_count = int(
        (
            await session.execute(
                select(func.count(Finding.id)).where(
                    Finding.project_id == project.id,
                    Finding.lifecycle_status.notin_(["RESOLVED", "ACCEPTED_RISK"]),
                )
            )
        ).scalar()
        or 0
    )

    resp = ProjectResponse.model_validate(project)
    resp.total_audits = audits_count
    resp.last_audit_status = latest_audit.status if latest_audit else None
    resp.last_audit_score = latest_audit.overall_score if latest_audit else None
    resp.last_release_gate = latest_audit.release_gate if latest_audit else None
    resp.unresolved_findings_count = unresolved_count
    return resp


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    root = Path(payload.root_path).resolve()
    if not root.exists() or not root.is_dir():
        raise QCPlatformError(
            message=f"Project root directory does not exist: '{payload.root_path}'",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_PROJECT_PATH",
        )

    base_slug = _slugify(payload.name)
    slug = base_slug
    counter = 1
    while (
        await session.execute(select(Project).where(Project.slug == slug))
    ).scalar_one_or_none() is not None:
        counter += 1
        slug = f"{base_slug}-{counter}"

    project = Project(
        name=payload.name,
        slug=slug,
        description=payload.description,
        root_path=str(root),
        repository_url=payload.repository_url,
        default_branch=payload.default_branch,
        owner_id=user.id,
        detected_stack={},
        is_deleted=False,
    )
    session.add(project)
    await session.flush()

    config = ProjectConfiguration(
        project_id=project.id,
        execution_mode=payload.execution_mode.upper(),
        exclusions=payload.exclusions,
        custom_rules={},
        service_startup_config={},
        quality_gate_policy={
            "max_critical_findings": 0,
            "min_approval_score": 60.0,
            "min_inspection_coverage_percent": 80.0,
        },
        llm_config={"default_provider": "ollama"},
        retention_days=90,
    )
    session.add(config)

    member = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role="OWNER",
        permissions={"all": True},
    )
    session.add(member)
    await session.commit()

    stmt = (
        select(Project)
        .options(selectinload(Project.configuration))
        .where(Project.id == project.id)
    )
    loaded = (await session.execute(stmt)).scalar_one()
    return await _enrich_project_response(session, loaded)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ProjectResponse]:
    stmt = (
        select(Project)
        .options(selectinload(Project.configuration))
        .where(Project.is_deleted.is_(False))
        .order_by(Project.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    projects = list((await session.execute(stmt)).scalars().all())
    return [await _enrich_project_response(session, p) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    stmt = (
        select(Project)
        .options(selectinload(Project.configuration))
        .where(Project.id == project_id, Project.is_deleted.is_(False))
    )
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise EntityNotFoundError("Project", project_id)
    return await _enrich_project_response(session, project)


@router.put("/{project_id}/config", response_model=ProjectConfigurationResponse)
async def update_project_configuration(
    project_id: UUID,
    payload: ProjectConfigUpdateRequest,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectConfigurationResponse:
    stmt = select(ProjectConfiguration).where(
        ProjectConfiguration.project_id == project_id
    )
    cfg = (await session.execute(stmt)).scalar_one_or_none()
    if cfg is None:
        raise EntityNotFoundError("ProjectConfiguration", project_id)

    if payload.execution_mode is not None:
        cfg.execution_mode = payload.execution_mode.upper()
    if payload.exclusions is not None:
        cfg.exclusions = payload.exclusions
    if payload.custom_rules is not None:
        cfg.custom_rules = payload.custom_rules
    if payload.service_startup_config is not None:
        cfg.service_startup_config = payload.service_startup_config
    if payload.quality_gate_policy is not None:
        cfg.quality_gate_policy = payload.quality_gate_policy
    if payload.llm_config is not None:
        cfg.llm_config = payload.llm_config
    if payload.retention_days is not None:
        cfg.retention_days = payload.retention_days

    await session.commit()
    await session.refresh(cfg)
    return ProjectConfigurationResponse.model_validate(cfg)


@router.delete("/{project_id}", status_code=status.HTTP_200_OK)
async def delete_project(
    project_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    project = await session.get(Project, project_id)
    if project is None or project.is_deleted:
        raise EntityNotFoundError("Project", project_id)
    project.is_deleted = True
    project.deleted_at = datetime.now(UTC)
    await session.commit()
    return {"id": str(project_id), "status": "DELETED"}


@router.post("/{project_id}/discover")
async def discover_project_repository(
    project_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    stmt = (
        select(Project)
        .options(selectinload(Project.configuration))
        .where(Project.id == project_id, Project.is_deleted.is_(False))
    )
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise EntityNotFoundError("Project", project_id)

    exclusions = project.configuration.exclusions if project.configuration else []
    engine = RepositoryIntelligenceEngine(custom_exclusions=exclusions)
    discovery = engine.discover_repository(project.root_path)
    manifest = discovery["manifest"]

    project.detected_stack = {
        "languages": manifest["languages"],
        "frameworks": manifest["frameworks"],
        "databases": manifest["databases"],
        "infrastructure": manifest["infrastructure"],
        "test_frameworks": manifest["test_frameworks"],
        "coverage": manifest["coverage"],
        "last_discovered_at": manifest["discovered_at"],
        "manifest": manifest,
    }

    # Check if there is an existing discovery session or create a lightweight discovery session record
    latest_session = (
        await session.execute(
            select(AuditSession)
            .where(AuditSession.project_id == project.id)
            .order_by(AuditSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest_session is None:
        latest_session = AuditSession(
            project_id=project.id,
            triggered_by=user.id,
            status="COMPLETED",
            current_phase="DISCOVERY_ONLY",
            audit_scope="DISCOVERY",
            runner_mode=project.configuration.execution_mode if project.configuration else "LOCAL",
            commit_hash=manifest.get("git", {}).get("commit_hash"),
            branch_name=manifest.get("git", {}).get("branch"),
            manifest_summary=manifest,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        session.add(latest_session)
        await session.flush()
    else:
        latest_session.manifest_summary = manifest

    await session.execute(
        delete(RepositoryFile).where(RepositoryFile.session_id == latest_session.id)
    )
    for f_rec in discovery["files"]:
        session.add(
            RepositoryFile(
                session_id=latest_session.id,
                project_id=project.id,
                relative_path=f_rec["relative_path"],
                file_type=f_rec["file_type"],
                language=f_rec["language"],
                size_bytes=f_rec["size_bytes"],
                line_count=f_rec["line_count"],
                sha256_hash=f_rec["sha256_hash"],
                inspection_status=f_rec["inspection_status"],
                status_reason=f_rec["status_reason"],
                is_entrypoint=f_rec["is_entrypoint"],
                is_test_file=f_rec["is_test_file"],
                component_boundary=f_rec["component_boundary"],
                imports_dependencies=f_rec["imports_dependencies"],
                inspected_at=f_rec.get("inspected_at"),
            )
        )

    await session.commit()
    return {
        "project_id": str(project.id),
        "session_id": str(latest_session.id),
        "manifest": manifest,
        "files_persisted": len(discovery["files"]),
    }


@router.get("/{project_id}/manifest")
async def get_project_manifest(
    project_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    project = await session.get(Project, project_id)
    if project is None or project.is_deleted:
        raise EntityNotFoundError("Project", project_id)

    latest_session = (
        await session.execute(
            select(AuditSession)
            .where(AuditSession.project_id == project.id)
            .order_by(AuditSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest_session and latest_session.manifest_summary:
        return {
            "project_id": str(project.id),
            "session_id": str(latest_session.id),
            "manifest": latest_session.manifest_summary,
        }

    manifest = (project.detected_stack or {}).get("manifest", {})
    return {
        "project_id": str(project.id),
        "session_id": None,
        "manifest": manifest,
    }


@router.get("/{project_id}/files", response_model=list[RepositoryFileResponse])
async def list_project_repository_files(
    project_id: UUID,
    inspection_status: str | None = Query(default=None),
    language: str | None = Query(default=None),
    boundary: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[RepositoryFileResponse]:
    latest_session = (
        await session.execute(
            select(AuditSession)
            .where(AuditSession.project_id == project_id)
            .order_by(AuditSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest_session is None:
        return []

    stmt = select(RepositoryFile).where(
        RepositoryFile.session_id == latest_session.id
    )
    if inspection_status:
        stmt = stmt.where(RepositoryFile.inspection_status == inspection_status.upper())
    if language:
        stmt = stmt.where(RepositoryFile.language == language)
    if boundary:
        stmt = stmt.where(RepositoryFile.component_boundary == boundary.upper())

    stmt = stmt.order_by(RepositoryFile.relative_path.asc()).offset(skip).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())
    return [RepositoryFileResponse.model_validate(r) for r in rows]


class GitCloneProjectRequest(BaseModel):
    repository_url: str
    name: str | None = None
    description: str | None = None
    branch: str = "main"
    git_token: str | None = None
    execution_mode: str = "LOCAL"
    env_content: str | None = None


class ProjectEnvUpdateRequest(BaseModel):
    env_content: str


async def _register_project_record(
    session: AsyncSession,
    user: User,
    name: str,
    root: Path,
    description: str | None = None,
    repository_url: str | None = None,
    default_branch: str = "main",
    execution_mode: str = "LOCAL",
) -> ProjectResponse:
    base_slug = _slugify(name)
    slug = base_slug
    counter = 1
    while (
        await session.execute(select(Project).where(Project.slug == slug))
    ).scalar_one_or_none() is not None:
        counter += 1
        slug = f"{base_slug}-{counter}"

    project = Project(
        name=name,
        slug=slug,
        description=description,
        root_path=str(root.resolve()),
        repository_url=repository_url,
        default_branch=default_branch,
        owner_id=user.id,
        detected_stack={},
        is_deleted=False,
    )
    session.add(project)
    await session.flush()

    config = ProjectConfiguration(
        project_id=project.id,
        execution_mode=execution_mode.upper(),
        exclusions=[],
        custom_rules={},
        service_startup_config={},
        quality_gate_policy={
            "max_critical_findings": 0,
            "min_approval_score": 60.0,
            "min_inspection_coverage_percent": 80.0,
        },
        llm_config={"default_provider": get_settings().DEFAULT_LLM_PROVIDER},
        retention_days=90,
    )
    session.add(config)

    member = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role="OWNER",
        permissions={"all": True},
    )
    session.add(member)
    await session.commit()

    stmt = (
        select(Project)
        .options(selectinload(Project.configuration))
        .where(Project.id == project.id)
    )
    loaded = (await session.execute(stmt)).scalar_one()
    return await _enrich_project_response(session, loaded)


@router.post("/upload-zip", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def upload_project_zip(
    file: UploadFile = File(...),
    name: str = Form(""),
    description: str = Form("Uploaded via ZIP archive"),
    execution_mode: str = Form("LOCAL"),
    env_content: str = Form(""),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    settings = get_settings()
    raw_bytes = await file.read()
    if not raw_bytes:
        raise QCPlatformError(
            message="Uploaded ZIP file is empty.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="EMPTY_ZIP_FILE",
        )

    proj_name = name.strip() or Path(file.filename or "uploaded-project").stem
    slug_dir = f"{_slugify(proj_name)}-{int(datetime.now(UTC).timestamp())}"
    dest_dir = (settings.storage_path / "uploaded_projects" / slug_dir).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            for member in zf.infolist():
                member_path = (dest_dir / member.filename).resolve()
                if not str(member_path).startswith(str(dest_dir)):
                    raise QCPlatformError(
                        message="ZIP archive contains unsafe relative path traversal.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                        code="UNSAFE_ZIP_PATH",
                    )
            zf.extractall(dest_dir)
    except zipfile.BadZipFile as exc:
        raise QCPlatformError(
            message=f"Invalid ZIP archive: {exc}",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_ZIP_ARCHIVE",
        ) from exc

    # If the ZIP contained a single top-level directory, unwrap it as root
    children = [p for p in dest_dir.iterdir() if p.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        dest_dir = children[0].resolve()

    if env_content.strip():
        (dest_dir / ".env").write_text(env_content.strip() + "\n", encoding="utf-8")

    return await _register_project_record(
        session=session,
        user=user,
        name=proj_name,
        root=dest_dir,
        description=description,
        execution_mode=execution_mode,
    )


@router.post("/upload-files", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def upload_project_files(
    files: list[UploadFile] = File(...),
    relative_paths: str = Form("[]"),
    name: str = Form("Uploaded Files Project"),
    description: str = Form("Uploaded source files via UI"),
    execution_mode: str = Form("LOCAL"),
    env_content: str = Form(""),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    settings = get_settings()
    if not files:
        raise QCPlatformError(
            message="No files provided for upload.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="NO_FILES_UPLOADED",
        )

    try:
        rel_list = json.loads(relative_paths) if relative_paths else []
    except Exception:
        rel_list = []

    proj_name = name.strip() or "Uploaded Files Project"
    slug_dir = f"{_slugify(proj_name)}-{int(datetime.now(UTC).timestamp())}"
    dest_dir = (settings.storage_path / "uploaded_projects" / slug_dir).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    for idx, upload in enumerate(files):
        rel_name = (
            rel_list[idx]
            if idx < len(rel_list) and rel_list[idx]
            else (upload.filename or f"file_{idx}.txt")
        )
        # Strip leading top-level folder if webkitRelativePath was passed
        rel_clean = Path(rel_name.lstrip("/\\"))
        target_path = (dest_dir / rel_clean).resolve()
        if not str(target_path).startswith(str(dest_dir)):
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = await upload.read()
        target_path.write_bytes(content)

    children = [p for p in dest_dir.iterdir() if p.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        dest_dir = children[0].resolve()

    if env_content.strip():
        (dest_dir / ".env").write_text(env_content.strip() + "\n", encoding="utf-8")

    return await _register_project_record(
        session=session,
        user=user,
        name=proj_name,
        root=dest_dir,
        description=description,
        execution_mode=execution_mode,
    )


@router.post("/clone-git", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def clone_git_project(
    payload: GitCloneProjectRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    settings = get_settings()
    repo_url = payload.repository_url.strip()
    if not repo_url:
        raise QCPlatformError(
            message="Repository URL cannot be empty.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="EMPTY_REPO_URL",
        )

    inferred_name = payload.name or repo_url.rstrip("/").split("/")[-1].replace(".git", "") or "git-project"
    slug_dir = f"{_slugify(inferred_name)}-{int(datetime.now(UTC).timestamp())}"
    dest_dir = (settings.storage_path / "cloned_projects" / slug_dir).resolve()
    dest_dir.parent.mkdir(parents=True, exist_ok=True)

    clone_url = repo_url
    token = (payload.git_token or settings.GITHUB_TOKEN or "").strip()
    if token and clone_url.startswith("https://") and "@" not in clone_url:
        clone_url = clone_url.replace("https://", f"https://{token}@", 1)

    def _run_clone() -> subprocess.CompletedProcess[str]:
        cmd = ["git", "clone", "--depth", "1"]
        if payload.branch:
            cmd.extend(["--branch", payload.branch])
        cmd.extend([clone_url, str(dest_dir)])
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    res = await asyncio.to_thread(_run_clone)
    if res.returncode != 0:
        # Fallback without --branch if default branch differs from 'main'
        def _run_clone_default() -> subprocess.CompletedProcess[str]:
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            return subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, str(dest_dir)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

        res = await asyncio.to_thread(_run_clone_default)
        if res.returncode != 0:
            err_msg = (res.stderr or res.stdout or "git clone failed").strip()
            raise QCPlatformError(
                message=f"Failed to clone Git repository: {err_msg}",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="GIT_CLONE_FAILED",
            )

    if payload.env_content and payload.env_content.strip():
        (dest_dir / ".env").write_text(payload.env_content.strip() + "\n", encoding="utf-8")

    return await _register_project_record(
        session=session,
        user=user,
        name=inferred_name,
        root=dest_dir,
        description=payload.description or f"Cloned from {repo_url}",
        repository_url=repo_url,
        default_branch=payload.branch or "main",
        execution_mode=payload.execution_mode,
    )


def _parse_env_keys(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#") and "=" in clean:
                k, v = clean.split("=", 1)
                result[k.strip()] = v.strip()
    except Exception:
        pass
    return result


@router.get("/{project_id}/readiness")
async def get_project_audit_readiness(
    project_id: UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Analyze the target project and generate tailored manual/automatic setup instructions."""
    project = await session.get(Project, project_id)
    if project is None or project.is_deleted:
        raise EntityNotFoundError("Project", project_id)

    root = Path(project.root_path).resolve()
    if not root.exists():
        return {
            "project_id": str(project.id),
            "ready_to_audit": False,
            "error": f"Project directory does not exist: {root}",
            "checklist": [],
        }

    has_requirements_txt = (root / "requirements.txt").exists() or (root / "backend" / "requirements.txt").exists()
    has_pyproject = (root / "pyproject.toml").exists() or (root / "backend" / "pyproject.toml").exists()
    has_package_json = (root / "package.json").exists() or (root / "frontend" / "package.json").exists()
    has_node_modules = (root / "node_modules").exists() or (root / "frontend" / "node_modules").exists()
    has_alembic = (root / "alembic.ini").exists() or (root / "backend" / "alembic.ini").exists()
    has_docker_compose = (
        (root / "docker-compose.yml").exists()
        or (root / "docker-compose.yaml").exists()
        or (root / "infrastructure" / "docker-compose.yml").exists()
    )

    env_example_path = (
        (root / ".env.example")
        if (root / ".env.example").exists()
        else ((root / ".env.template") if (root / ".env.template").exists() else None)
    )
    env_actual_path = root / ".env"

    example_vars = _parse_env_keys(env_example_path) if env_example_path else {}
    actual_vars = _parse_env_keys(env_actual_path)

    missing_env_keys = [
        k for k, default_val in example_vars.items()
        if k not in actual_vars and (not default_val or "replace" in default_val.lower() or "your-" in default_val.lower())
    ]

    checklist: list[dict[str, Any]] = []

    # 1. Source Code & Workspace Isolation
    checklist.append(
        {
            "category": "Workspace & Static Analysis",
            "title": "Repository Snapshot & AST/Security Scanners",
            "status": "READY (AUTOMATIC)",
            "manual_action_needed": False,
            "instruction": (
                "No manual setup needed. The QC Agent automatically copies your source files into an isolated workspace "
                "and runs AST code quality, architecture, and security scanners."
            ),
            "command": None,
        }
    )

    # 2. Python Dependencies
    if has_requirements_txt or has_pyproject:
        req_cmd = (
            "pip install -r requirements.txt"
            if (root / "requirements.txt").exists()
            else ("pip install -e ." if (root / "pyproject.toml").exists() else "pip install -r backend/requirements.txt")
        )
        checklist.append(
            {
                "category": "Python Backend & Pytest Suite",
                "title": "Python Package Dependencies",
                "status": "CHECK ENVIRONMENT",
                "manual_action_needed": True,
                "instruction": (
                    "Python project detected. Static/AST analysis runs without installing packages, "
                    "but to allow BackendQAAgent to boot your server and run Pytest, ensure the project's "
                    "Python packages are installed in the local Python environment."
                ),
                "command": f"cd \"{root}\" && {req_cmd}",
            }
        )

    # 3. Node / Frontend Dependencies
    if has_package_json:
        fe_dir = root / "frontend" if (root / "frontend" / "package.json").exists() else root
        checklist.append(
            {
                "category": "Frontend Build & Playwright Browser QA",
                "title": "Node.js / Frontend Dependencies (node_modules)",
                "status": "READY" if has_node_modules else "ACTION RECOMMENDED",
                "manual_action_needed": not has_node_modules,
                "instruction": (
                    "node_modules is present — FrontendQAAgent can build and launch your UI."
                    if has_node_modules
                    else "package.json detected without node_modules. Run `npm install` so FrontendQAAgent can build and test the live UI in headless Chromium."
                ),
                "command": None if has_node_modules else f"cd \"{fe_dir}\" && npm install",
            }
        )

    # 4. Target Project .env Configuration
    if env_example_path:
        checklist.append(
            {
                "category": "Target Project Environment (.env)",
                "title": f"Environment Variables ({env_example_path.name})",
                "status": "ACTION RECOMMENDED" if missing_env_keys else "READY",
                "manual_action_needed": len(missing_env_keys) > 0,
                "instruction": (
                    f"Found {env_example_path.name} with {len(missing_env_keys)} unconfigured key(s): {', '.join(missing_env_keys)}. "
                    "You can paste or edit your target project's .env content directly in the editor below, or let the QC Agent use its synthetic sandbox .env.qc."
                    if missing_env_keys
                    else f"All keys from {env_example_path.name} have defaults or are present in .env."
                ),
                "command": None,
            }
        )
    else:
        checklist.append(
            {
                "category": "Target Project Environment (.env)",
                "title": "Synthetic Sandbox Environment (.env.qc)",
                "status": "READY (AUTOMATIC)",
                "manual_action_needed": False,
                "instruction": (
                    "The QC Agent automatically injects synthetic sandbox variables (APP_ENV=test_sandbox, SECRET_KEY, DATABASE_URL). "
                    "If your app requires custom API keys to start, you can add them in the .env editor below."
                ),
                "command": None,
            }
        )

    # 5. Database & Migrations
    if has_alembic or has_docker_compose:
        checklist.append(
            {
                "category": "Database & External Services",
                "title": "Database Schema & Service Dependencies",
                "status": "INFO",
                "manual_action_needed": False,
                "instruction": (
                    "Alembic migrations / Docker Compose detected. DatabaseAuditAgent inspects migration scripts statically "
                    "and verifies live schema constraints when your database is reachable."
                ),
                "command": f"cd \"{root}\" && alembic upgrade head" if has_alembic else None,
            }
        )

    current_env_text = (
        env_actual_path.read_text(encoding="utf-8", errors="replace")
        if env_actual_path.exists()
        else (
            env_example_path.read_text(encoding="utf-8", errors="replace")
            if env_example_path
            else ""
        )
    )

    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "root_path": str(root),
        "ready_to_audit": True,
        "has_env_file": env_actual_path.exists(),
        "has_env_example": env_example_path is not None,
        "missing_env_keys": missing_env_keys,
        "current_env_content": current_env_text,
        "checklist": checklist,
    }


@router.post("/{project_id}/env")
async def save_project_env_file(
    project_id: UUID,
    payload: ProjectEnvUpdateRequest,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Save custom .env variables directly into the target project directory."""
    project = await session.get(Project, project_id)
    if project is None or project.is_deleted:
        raise EntityNotFoundError("Project", project_id)

    root = Path(project.root_path).resolve()
    env_file = root / ".env"
    env_file.write_text(payload.env_content.strip() + "\n", encoding="utf-8")
    return {
        "project_id": str(project.id),
        "env_path": str(env_file),
        "status": "SAVED",
    }
