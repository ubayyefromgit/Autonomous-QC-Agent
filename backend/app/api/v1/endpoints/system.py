"""System Health, Overview Telemetry, Agents & Executors REST API endpoints (/api/v1/system)."""

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.registry.agent_registry import AgentRegistry
from backend.app.api.dependencies.auth import get_current_user
from backend.app.core.config import get_settings
from backend.app.infrastructure.database.session import get_db_session
from backend.app.infrastructure.execution.project_runner import DockerProjectRunner
from backend.app.models.entities import (
    AgentExecution,
    AuditEvent,
    AuditSession,
    Finding,
    Project,
    RemediationProposal,
    User,
)
from shared.constants.defaults import ALLOWED_RUNNER_COMMANDS, QUALITY_DIMENSION_WEIGHTS

router = APIRouter(prefix="/system", tags=["System & Agents"])


@router.get("/overview")
async def get_overview_dashboard_telemetry(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    registered_projects = int(
        (
            await session.execute(
                select(func.count(Project.id)).where(Project.is_deleted.is_(False))
            )
        ).scalar()
        or 0
    )
    total_audits = int(
        (await session.execute(select(func.count(AuditSession.id)))).scalar() or 0
    )
    active_audits = int(
        (
            await session.execute(
                select(func.count(AuditSession.id)).where(
                    AuditSession.status.in_(
                        ["CREATED", "DISCOVERING", "PLANNING", "EXECUTING", "VALIDATING", "SCORING", "REPORTING"]
                    )
                )
            )
        ).scalar()
        or 0
    )
    completed_audits = int(
        (
            await session.execute(
                select(func.count(AuditSession.id)).where(
                    AuditSession.status == "COMPLETED"
                )
            )
        ).scalar()
        or 0
    )
    failed_audits = int(
        (
            await session.execute(
                select(func.count(AuditSession.id)).where(
                    AuditSession.status == "FAILED"
                )
            )
        ).scalar()
        or 0
    )
    total_findings = int(
        (await session.execute(select(func.count(Finding.id)))).scalar() or 0
    )
    critical_findings = int(
        (
            await session.execute(
                select(func.count(Finding.id)).where(Finding.severity == "CRITICAL")
            )
        ).scalar()
        or 0
    )
    security_findings = int(
        (
            await session.execute(
                select(func.count(Finding.id)).where(
                    Finding.category.in_(
                        ["SECURITY_VULNERABILITY", "SECRET_EXPOSURE", "DEPENDENCY_VULNERABILITY"]
                    )
                )
            )
        ).scalar()
        or 0
    )
    pending_approvals = int(
        (
            await session.execute(
                select(func.count(RemediationProposal.id)).where(
                    RemediationProposal.status.in_(["AWAITING_APPROVAL", "SAFETY_CHECKED"])
                )
            )
        ).scalar()
        or 0
    )

    # Calculate average audit duration in seconds across completed sessions
    completed_rows = list(
        (
            await session.execute(
                select(AuditSession).where(
                    AuditSession.status == "COMPLETED",
                    AuditSession.started_at.is_not(None),
                    AuditSession.completed_at.is_not(None),
                )
            )
        ).scalars()
    )
    if completed_rows:
        durations = [
            max(0.0, (r.completed_at - r.started_at).total_seconds())
            for r in completed_rows
            if r.completed_at and r.started_at
        ]
        avg_duration = round(sum(durations) / max(1, len(durations)), 2)
    else:
        avg_duration = 0.0

    # Severity distribution
    sev_rows = (
        await session.execute(
            select(Finding.severity, func.count(Finding.id)).group_by(Finding.severity)
        )
    ).all()
    severity_breakdown = {sev: int(cnt) for sev, cnt in sev_rows}

    return {
        "registered_projects": registered_projects,
        "total_audits": total_audits,
        "active_audits": active_audits,
        "completed_audits": completed_audits,
        "failed_audits": failed_audits,
        "total_findings": total_findings,
        "critical_findings": critical_findings,
        "security_findings": security_findings,
        "pending_approvals": pending_approvals,
        "average_audit_duration_seconds": avg_duration,
        "severity_breakdown": severity_breakdown,
    }


@router.get("/health")
async def get_system_health(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    settings = get_settings()
    db_ok = False
    db_version = "unknown"
    is_sqlite = "sqlite" in settings.DATABASE_URL.lower()
    try:
        query_str = "SELECT sqlite_version()" if is_sqlite else "SELECT version()"
        res = await session.execute(text(query_str))
        ver_val = str(res.scalar() or "")
        db_version = f"SQLite {ver_val} (Embedded Universal Mode)" if is_sqlite else ver_val
        db_ok = True
    except Exception as exc:
        db_version = f"Error: {exc}"

    return {
        "status": "HEALTHY" if db_ok else "DEGRADED",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "database": {
            "connected": db_ok,
            "engine": "SQLite (Embedded)" if is_sqlite else "PostgreSQL",
            "version": db_version,
        },
        "storage": {
            "storage_root": str(settings.storage_path),
            "workspace_root": str(settings.workspace_path),
            "writable": settings.storage_path.exists(),
        },
        "ai_gateway": {
            "default_provider": settings.DEFAULT_LLM_PROVIDER,
            "supported_providers": ["ollama", "gemini", "openai"],
            "gemini_configured": bool(settings.GEMINI_API_KEY),
            "openai_configured": bool(settings.OPENAI_API_KEY),
        },
    }


@router.get("/agents")
async def list_registered_agents(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    registry = AgentRegistry()
    agents = registry.list_agents()
    counts_rows = (
        await session.execute(
            select(AgentExecution.agent_name, func.count(AgentExecution.id)).group_by(
                AgentExecution.agent_name
            )
        )
    ).all()
    exec_counts = {name: int(cnt) for name, cnt in counts_rows}
    for ag in agents:
        ag["total_executions"] = exec_counts.get(ag["name"], 0)
    return {"agents": agents, "total_registered": len(agents)}


@router.get("/executors")
async def get_executors_status(
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    scanners = {}
    for tool in ("python", "pytest", "ruff", "mypy", "bandit", "playwright", "git", "node", "npm", "docker"):
        scanners[tool] = {
            "installed": shutil.which(tool) is not None,
            "path": shutil.which(tool),
        }

    return {
        "executors": [
            {
                "mode": "LOCAL",
                "adapter": "LocalProjectRunner",
                "available": True,
                "isolation_model": "Isolated workspace copy + restricted env (.env.qc) + process tree termination + command allowlist",
                "warning": "Local execution has reduced OS kernel isolation compared to container sandboxes.",
            },
            {
                "mode": "DOCKER",
                "adapter": "DockerProjectRunner",
                "available": DockerProjectRunner.is_docker_available(),
                "isolation_model": "Disposable non-root container (uid 10001), --cap-drop=ALL, --read-only mount, CPU/RAM/PID caps, no docker.sock",
            },
        ],
        "allowed_commands": list(ALLOWED_RUNNER_COMMANDS),
        "quality_dimension_weights": QUALITY_DIMENSION_WEIGHTS,
        "installed_tools": scanners,
    }


@router.get("/agent-activity")
async def get_agent_activity(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    executions = list(
        (
            await session.execute(
                select(AgentExecution)
                .order_by(AgentExecution.started_at.desc())
                .limit(50)
            )
        ).scalars()
    )
    events = list(
        (
            await session.execute(
                select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(50)
            )
        ).scalars()
    )
    return {
        "executions": [
            {
                "id": str(ex.id),
                "session_id": str(ex.session_id),
                "task_id": str(ex.task_id),
                "agent_name": ex.agent_name,
                "status": ex.status,
                "duration_seconds": ex.duration_seconds,
                "llm_provider": ex.llm_provider,
                "prompt_tokens": ex.prompt_tokens,
                "completion_tokens": ex.completion_tokens,
                "started_at": ex.started_at.isoformat() if ex.started_at else None,
                "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
            }
            for ex in executions
        ],
        "events": [
            {
                "id": str(ev.id),
                "session_id": str(ev.session_id) if ev.session_id else None,
                "event_type": ev.event_type,
                "actor": ev.actor,
                "severity": ev.severity,
                "message": ev.message,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in events
        ],
    }


class RuntimeConfigUpdatePayload(BaseModel):
    default_llm_provider: str | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    github_token: str | None = None
    default_runner_mode: str | None = None


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _probe_tool_version(cmd: list[str]) -> str:
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        out = (res.stdout or res.stderr or "").strip().splitlines()
        return out[0][:80] if out else "Installed"
    except Exception:
        return "Installed"


@router.get("/runtime-config")
async def get_runtime_configuration(
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = get_settings()

    # Check if local Ollama is reachable
    ollama_reachable = False
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            ollama_reachable = resp.status_code == 200
    except Exception:
        ollama_reachable = False

    tool_specs = [
        (
            "python",
            ["python", "--version"],
            "REQUIRED",
            "Core backend execution, AST parsing, and test runner",
            "Download Python 3.11+ from https://www.python.org/downloads/",
        ),
        (
            "git",
            ["git", "--version"],
            "REQUIRED",
            "Repository cloning, commit snapshot hashing, and isolated remediation branches",
            "Install Git from https://git-scm.com/downloads",
        ),
        (
            "pytest",
            ["pytest", "--version"],
            "REQUIRED",
            "Deterministic Python unit/integration/regression test execution",
            "pip install pytest pytest-asyncio httpx",
        ),
        (
            "ruff",
            ["ruff", "--version"],
            "RECOMMENDED",
            "Fast Python static analysis and lint verification",
            "pip install ruff",
        ),
        (
            "bandit",
            ["bandit", "--version"],
            "RECOMMENDED",
            "Python SAST security vulnerability scanner",
            "pip install bandit",
        ),
        (
            "mypy",
            ["mypy", "--version"],
            "OPTIONAL",
            "Static type checking for Python codebases",
            "pip install mypy",
        ),
        (
            "node",
            ["node", "--version"],
            "RECOMMENDED (for JS/TS projects)",
            "JavaScript/TypeScript frontend build and runtime verification",
            "Install Node.js LTS from https://nodejs.org/",
        ),
        (
            "npm",
            ["npm", "--version"],
            "RECOMMENDED (for JS/TS projects)",
            "Frontend package dependency installation and build scripts",
            "Included with Node.js LTS installation",
        ),
        (
            "playwright",
            ["playwright", "--version"],
            "OPTIONAL (for Live Browser E2E)",
            "Headless Chromium browser automation for Frontend QA Agent",
            "pip install playwright && playwright install chromium",
        ),
        (
            "docker",
            ["docker", "--version"],
            "OPTIONAL (for Container Sandbox Mode)",
            "Disposable container isolation for DockerProjectRunner",
            "Install Docker Desktop from https://www.docker.com/products/docker-desktop/",
        ),
    ]

    tools_report = []
    for name, ver_cmd, requirement_level, purpose, install_cmd in tool_specs:
        exe_path = shutil.which(name)
        installed = exe_path is not None
        version_str = _probe_tool_version(ver_cmd) if installed else "Not Installed"
        tools_report.append(
            {
                "name": name,
                "installed": installed,
                "path": exe_path,
                "version": version_str,
                "requirement_level": requirement_level,
                "purpose": purpose,
                "install_command": install_cmd,
            }
        )

    instructions = {
        "quick_start_steps": [
            {
                "step": 1,
                "title": "1. Configure AI Provider & Optional API Keys",
                "summary": (
                    "NO PAID API KEY IS REQUIRED to run deterministic audits. By default, the platform uses "
                    "deterministic AST/Runtime/Security scanners + local Ollama (if running). If you want cloud "
                    "LLM root-cause synthesis, enter a Google Gemini API Key or OpenAI API Key below."
                ),
                "manual_action_required": "Only if you select Google Gemini or OpenAI as your active AI provider, or if cloning a private GitHub repository (requires GitHub Personal Access Token).",
            },
            {
                "step": 2,
                "title": "2. Provide Your Target Project (3 Supported Methods)",
                "summary": (
                    "Upload a .zip archive of your project, upload multiple source files directly, click 'Browse Local Folder' "
                    "to pick a directory on your PC, or paste a Git repository URL (GitHub/GitLab/Bitbucket)."
                ),
                "manual_action_required": "If your target project requires its own .env secrets (such as its own database URL or third-party keys) to boot up during live runtime probing, paste or upload them in the 'Target Project .env Variables' box.",
            },
            {
                "step": 3,
                "title": "3. Automatic vs. Manual Dependency & Service Setup",
                "summary": (
                    "The QC Agent automatically copies your project into an isolated workspace (.qc_workspaces), "
                    "creates a synthetic sandbox environment (.env.qc), and runs static, AST, security, database, "
                    "API, and performance checks."
                ),
                "manual_action_required": (
                    "For Python projects, ensure project packages are installed in your Python environment (`pip install -r requirements.txt`). "
                    "For Node/React projects, run `npm install` in the project folder if you want live build/browser verification. "
                    "Use the 'Project Readiness & Setup Advisor' tab after registering a project to see exact commands tailored to that repository."
                ),
            },
            {
                "step": 4,
                "title": "4. Review Evidence, Approve Fixes & Export Reports",
                "summary": (
                    "Every confirmed finding includes cryptographic SHA-256 evidence. Click 'Generate Remediation Proposal' "
                    "on any finding to synthesize a unified Git diff, review and approve the exact patch checksum in the Approval Center, "
                    "and export 21-section HTML or PDF Executive Audit Reports."
                ),
                "manual_action_required": "Human approval is strictly required before any proposed code fix is applied.",
            },
        ]
    }

    return {
        "ai_config": {
            "default_llm_provider": settings.DEFAULT_LLM_PROVIDER,
            "ollama_base_url": settings.OLLAMA_BASE_URL,
            "ollama_model": settings.OLLAMA_MODEL,
            "ollama_reachable": ollama_reachable,
            "gemini_model": settings.GEMINI_MODEL,
            "has_gemini_key": bool(settings.GEMINI_API_KEY),
            "gemini_key_masked": _mask_secret(settings.GEMINI_API_KEY),
            "openai_model": settings.OPENAI_MODEL,
            "has_openai_key": bool(settings.OPENAI_API_KEY),
            "openai_key_masked": _mask_secret(settings.OPENAI_API_KEY),
            "has_github_token": bool(settings.GITHUB_TOKEN),
            "github_token_masked": _mask_secret(settings.GITHUB_TOKEN),
            "default_runner_mode": settings.DEFAULT_RUNNER_MODE,
        },
        "system_tools": tools_report,
        "instructions": instructions,
    }


@router.post("/runtime-config")
async def update_runtime_configuration(
    payload: RuntimeConfigUpdatePayload,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = get_settings()

    if payload.default_llm_provider is not None:
        settings.DEFAULT_LLM_PROVIDER = payload.default_llm_provider.strip().lower()
    if payload.ollama_base_url is not None:
        settings.OLLAMA_BASE_URL = payload.ollama_base_url.strip()
    if payload.ollama_model is not None:
        settings.OLLAMA_MODEL = payload.ollama_model.strip()
    if payload.gemini_api_key is not None and payload.gemini_api_key.strip() != "":
        settings.GEMINI_API_KEY = payload.gemini_api_key.strip()
    if payload.gemini_model is not None:
        settings.GEMINI_MODEL = payload.gemini_model.strip()
    if payload.openai_api_key is not None and payload.openai_api_key.strip() != "":
        settings.OPENAI_API_KEY = payload.openai_api_key.strip()
    if payload.openai_model is not None:
        settings.OPENAI_MODEL = payload.openai_model.strip()
    if payload.github_token is not None and payload.github_token.strip() != "":
        settings.GITHUB_TOKEN = payload.github_token.strip()
    if payload.default_runner_mode is not None:
        settings.DEFAULT_RUNNER_MODE = payload.default_runner_mode.strip().upper()

    # Persist to local .env file for durability across restarts
    env_path = Path(".env").resolve()
    existing_lines: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#") and "=" in clean:
                k, v = clean.split("=", 1)
                existing_lines[k.strip()] = v.strip()

    existing_lines.update(
        {
            "DEFAULT_LLM_PROVIDER": settings.DEFAULT_LLM_PROVIDER,
            "OLLAMA_BASE_URL": settings.OLLAMA_BASE_URL,
            "OLLAMA_MODEL": settings.OLLAMA_MODEL,
            "GEMINI_API_KEY": settings.GEMINI_API_KEY,
            "GEMINI_MODEL": settings.GEMINI_MODEL,
            "OPENAI_API_KEY": settings.OPENAI_API_KEY,
            "OPENAI_MODEL": settings.OPENAI_MODEL,
            "GITHUB_TOKEN": settings.GITHUB_TOKEN,
            "DEFAULT_RUNNER_MODE": settings.DEFAULT_RUNNER_MODE,
        }
    )
    env_body = "\n".join(f"{k}={v}" for k, v in existing_lines.items()) + "\n"
    env_path.write_text(env_body, encoding="utf-8")

    return await get_runtime_configuration(_user)


@router.post("/pick-folder")
async def pick_local_folder(
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Open a native OS folder browser dialog on the host machine and return the selected path."""

    def _open_dialog() -> str:
        # 1. Native Tkinter directory dialog (instant, native, guaranteed foreground)
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            root.lift()
            root.focus_force()
            selected = filedialog.askdirectory(
                title="Select Target Software Project Folder for QC Audit"
            )
            root.destroy()
            if selected:
                return str(Path(selected).resolve())
        except Exception:
            pass

        # 2. Native Windows FolderBrowserDialog with focused foreground window
        if sys.platform == "win32":
            ps_script = (
                "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); "
                "$form = New-Object System.Windows.Forms.Form; "
                "$form.TopMost = $true; "
                "$form.StartPosition = 'CenterScreen'; "
                "$form.WindowState = 'Minimized'; "
                "$form.Show(); "
                "$form.WindowState = 'Normal'; "
                "$form.BringToFront(); "
                "$form.Activate(); "
                "$dlg = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$dlg.Description = 'Select Target Software Project Folder for Autonomous QC Audit'; "
                "$dlg.ShowNewFolderButton = $false; "
                "$res = $dlg.ShowDialog($form); "
                "$selected = $dlg.SelectedPath; "
                "$form.Close(); "
                "if ($res -eq [System.Windows.Forms.DialogResult]::OK -and $selected) { "
                "  Write-Output $selected "
                "}"
            )
            try:
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-STA", "-Command", ps_script],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                out = (proc.stdout or "").strip()
                if out:
                    return out.splitlines()[-1].strip()
            except Exception:
                pass

            # Fallback A: Windows OpenFileDialog in folder-selection mode
            try:
                ps_openfile_script = (
                    "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); "
                    "$f = New-Object System.Windows.Forms.OpenFileDialog; "
                    "$f.ValidateNames = $false; "
                    "$f.CheckFileExists = $false; "
                    "$f.CheckPathExists = $true; "
                    "$f.FileName = 'Select Current Folder.'; "
                    "$f.Title = 'Select Target Project Folder for QC Audit'; "
                    "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
                    "  Write-Output ([System.IO.Path]::GetDirectoryName($f.FileName)) "
                    "}"
                )
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-STA", "-Command", ps_openfile_script],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                out = (proc.stdout or "").strip()
                if out:
                    return out.splitlines()[-1].strip()
            except Exception:
                pass

        # 2. Native macOS folder picker fallback
        if sys.platform == "darwin":
            try:
                proc = subprocess.run(
                    [
                        "osascript",
                        "-e",
                        'POSIX path of (choose folder with prompt "Select Target Software Project Folder for QC Audit")',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                out = (proc.stdout or "").strip()
                if out:
                    return out
            except Exception:
                pass

        # 3. Cross-platform tkinter fallback
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder_selected = filedialog.askdirectory(
                title="Select Target Software Project Folder for QC Audit"
            )
            root.destroy()
            return folder_selected or ""
        except Exception:
            return ""

    chosen = await asyncio.to_thread(_open_dialog)
    return {
        "selected_path": str(Path(chosen).resolve()) if chosen else "",
        "cancelled": not bool(chosen),
    }


class ProviderModelsRequest(BaseModel):
    provider: str
    api_key: str | None = None
    ollama_base_url: str | None = None


@router.post("/provider-models")
async def list_provider_models(
    payload: ProviderModelsRequest,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch available AI models dynamically for the selected provider and API key."""
    settings = get_settings()
    provider = payload.provider.strip().lower()

    if provider == "gemini":
        key = (payload.api_key or "").strip() or settings.GEMINI_API_KEY
        default_models = [
            {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro (gemini-2.5-pro)"},
            {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash (gemini-2.5-flash)"},
            {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash (gemini-2.0-flash)"},
            {"id": "gemini-1.5-pro", "label": "Gemini 1.5 Pro (gemini-1.5-pro)"},
            {"id": "gemini-1.5-flash", "label": "Gemini 1.5 Flash (gemini-1.5-flash)"},
        ]
        if not key:
            return {
                "provider": "gemini",
                "source": "default_catalog",
                "models": default_models,
                "selected_model": settings.GEMINI_MODEL,
                "error": "Enter a Gemini API Key and click 'Fetch Models' to load live models for your key.",
            }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": key},
                )
            if resp.status_code != 200:
                err_detail = resp.json().get("error", {}).get("message", f"HTTP {resp.status_code}")
                return {
                    "provider": "gemini",
                    "source": "default_catalog",
                    "models": default_models,
                    "selected_model": settings.GEMINI_MODEL,
                    "error": f"Gemini API Key check failed: {err_detail}",
                }
            raw_models = resp.json().get("models", [])
            live_models: list[dict[str, str]] = []
            for m in raw_models:
                methods = m.get("supportedGenerationMethods", [])
                name = str(m.get("name", ""))
                if "generateContent" in methods and name.startswith("models/"):
                    short_id = name.replace("models/", "", 1)
                    if "gemini" in short_id.lower():
                        disp = m.get("displayName") or short_id
                        live_models.append(
                            {"id": short_id, "label": f"{disp} ({short_id})"}
                        )
            live_models.sort(key=lambda x: x["id"], reverse=True)
            return {
                "provider": "gemini",
                "source": "live_api",
                "models": live_models or default_models,
                "selected_model": settings.GEMINI_MODEL,
                "error": None,
            }
        except Exception as exc:
            return {
                "provider": "gemini",
                "source": "default_catalog",
                "models": default_models,
                "selected_model": settings.GEMINI_MODEL,
                "error": f"Could not reach Gemini API: {exc}",
            }

    if provider == "openai":
        key = (payload.api_key or "").strip() or settings.OPENAI_API_KEY
        default_models = [
            {"id": "gpt-4o", "label": "GPT-4o (gpt-4o)"},
            {"id": "gpt-4o-mini", "label": "GPT-4o Mini (gpt-4o-mini)"},
            {"id": "o3-mini", "label": "OpenAI o3-mini (o3-mini)"},
            {"id": "o1", "label": "OpenAI o1 (o1)"},
            {"id": "gpt-4-turbo", "label": "GPT-4 Turbo (gpt-4-turbo)"},
        ]
        if not key:
            return {
                "provider": "openai",
                "source": "default_catalog",
                "models": default_models,
                "selected_model": settings.OPENAI_MODEL,
                "error": "Enter an OpenAI API Key and click 'Fetch Models' to load live models for your key.",
            }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
            if resp.status_code != 200:
                err_detail = resp.json().get("error", {}).get("message", f"HTTP {resp.status_code}")
                return {
                    "provider": "openai",
                    "source": "default_catalog",
                    "models": default_models,
                    "selected_model": settings.OPENAI_MODEL,
                    "error": f"OpenAI API Key check failed: {err_detail}",
                }
            raw_models = resp.json().get("data", [])
            skip_tokens = ("audio", "realtime", "tts", "whisper", "dall-e", "embedding", "moderation", "babbage", "davinci", "transcribe", "search")
            live_models = []
            for m in raw_models:
                mid = str(m.get("id", ""))
                if mid.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-")) and not any(
                    tok in mid.lower() for tok in skip_tokens
                ):
                    live_models.append({"id": mid, "label": mid})
            live_models.sort(key=lambda x: x["id"], reverse=True)
            return {
                "provider": "openai",
                "source": "live_api",
                "models": live_models or default_models,
                "selected_model": settings.OPENAI_MODEL,
                "error": None,
            }
        except Exception as exc:
            return {
                "provider": "openai",
                "source": "default_catalog",
                "models": default_models,
                "selected_model": settings.OPENAI_MODEL,
                "error": f"Could not reach OpenAI API: {exc}",
            }

    # Default: ollama
    base_url = ((payload.ollama_base_url or "").strip() or settings.OLLAMA_BASE_URL).rstrip("/")
    default_ollama = [
        {"id": "qwen2.5-coder:7b", "label": "Qwen 2.5 Coder 7B (qwen2.5-coder:7b)"},
        {"id": "llama3.1:8b", "label": "Llama 3.1 8B (llama3.1:8b)"},
        {"id": "deepseek-coder-v2:16b", "label": "DeepSeek Coder V2 16B (deepseek-coder-v2:16b)"},
        {"id": "codellama:7b", "label": "CodeLlama 7B (codellama:7b)"},
    ]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
        if resp.status_code == 200:
            tags = resp.json().get("models", [])
            live_ollama = [
                {"id": str(t.get("name")), "label": f"{t.get('name')} (Local Ollama)"}
                for t in tags
                if t.get("name")
            ]
            if live_ollama:
                return {
                    "provider": "ollama",
                    "source": "live_api",
                    "models": live_ollama,
                    "selected_model": settings.OLLAMA_MODEL,
                    "error": None,
                }
        return {
            "provider": "ollama",
            "source": "default_catalog",
            "models": default_ollama,
            "selected_model": settings.OLLAMA_MODEL,
            "error": None,
        }
    except Exception:
        return {
            "provider": "ollama",
            "source": "default_catalog",
            "models": default_ollama,
            "selected_model": settings.OLLAMA_MODEL,
            "error": None,
        }
