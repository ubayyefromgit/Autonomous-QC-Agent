"""Project-Integrated QC Agent CLI (`qc-agent`) sharing the core Audit Engine."""

import asyncio
import json
from pathlib import Path
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from backend.app.agents.orchestrator.master_orchestrator import MasterAuditOrchestrator
from backend.app.api.dependencies.auth import ensure_default_admin
from backend.app.application.services.remediation_service import RemediationService
from backend.app.audit_engine.discovery.repository_intelligence_engine import (
    RepositoryIntelligenceEngine,
)
from backend.app.audit_engine.reporting.report_service import ReportService
from backend.app.infrastructure.database.session import AsyncSessionLocal
from backend.app.models.entities import (
    AuditSession,
    Finding,
    Project,
    ProjectConfiguration,
)
from qc_agent_cli.qc_agent.configuration.config_loader import (
    load_and_validate_qc_config,
)

app = typer.Typer(
    name="qc-agent",
    help="Autonomous QC & Project Audit Intelligence CLI (Mode B).",
    add_completion=False,
)
config_app = typer.Typer(help="Validate and inspect .qc/config.yaml.")
app.add_typer(config_app, name="config")

console = Console()


async def _ensure_project_registered(root_path: Path) -> Project:
    cfg, _ = load_and_validate_qc_config(root_path)
    async with AsyncSessionLocal() as db:
        admin = await ensure_default_admin(db)
        stmt = (
            select(Project)
            .where(Project.root_path == str(root_path), Project.is_deleted.is_(False))
            .order_by(Project.created_at.desc())
        )
        project = (await db.execute(stmt)).scalars().first()
        if project is None:
            proj_name = cfg.project.get("name", root_path.name)
            slug = f"cli-{proj_name.lower().replace(' ', '-')}-{str(admin.id)[:6]}"
            project = Project(
                name=proj_name,
                slug=slug,
                description="Registered via qc-agent CLI",
                root_path=str(root_path),
                owner_id=admin.id,
                detected_stack={},
            )
            db.add(project)
            await db.flush()
            db.add(
                ProjectConfiguration(
                    project_id=project.id,
                    execution_mode=cfg.execution.get("mode", "LOCAL").upper(),
                    exclusions=cfg.exclusions,
                    custom_rules=cfg.custom_rules,
                    quality_gate_policy=cfg.quality_gate,
                )
            )
            await db.commit()
            await db.refresh(project)
        return project


@app.command("discover")
def discover_command(
    path: str = typer.Option(".", "--path", "-p", help="Target repository directory"),
    output_json: bool = typer.Option(False, "--json", help="Print full JSON manifest"),
) -> None:
    """Inspect repository structure, languages, frameworks, entrypoints, and file coverage."""
    root = Path(path).resolve()
    cfg, _ = load_and_validate_qc_config(root)
    engine = RepositoryIntelligenceEngine(custom_exclusions=cfg.exclusions)
    result = engine.discover_repository(root)
    manifest = result["manifest"]
    cov = manifest["coverage"]

    if output_json:
        console.print_json(json.dumps(manifest, default=str))
        return

    console.print(f"[bold cyan]Repository Discovery Complete:[/bold cyan] {manifest['project_name']}")
    console.print(f"Root Path: {manifest['root_path']}")
    console.print(f"Languages: {', '.join(manifest['languages']) or 'None'}")
    console.print(f"Frameworks: {', '.join(manifest['frameworks']) or 'None'}")
    console.print(f"Databases: {', '.join(manifest['databases']) or 'None'}")
    console.print(
        f"Coverage: {cov['files_inspected']} inspected / {cov['files_in_scope']} in-scope "
        f"({cov['files_excluded']} excluded) -> {cov['inspection_coverage_percent']}%"
    )


@app.command("audit")
def audit_command(
    path: str = typer.Option(".", "--path", "-p", help="Target repository directory"),
    full: bool = typer.Option(False, "--full", help="Run full comprehensive audit"),
    code: bool = typer.Option(False, "--code", help="Run static code & architecture audit"),
    backend: bool = typer.Option(False, "--backend", help="Run backend & API runtime audit"),
    frontend: bool = typer.Option(False, "--frontend", help="Run frontend Playwright browser audit"),
    security: bool = typer.Option(False, "--security", help="Run deterministic security scan"),
    e2e: bool = typer.Option(False, "--e2e", help="Run full-stack E2E & integration checks"),
    runner: str = typer.Option("local", "--runner", help="Execution runner: local or docker"),
) -> None:
    """Execute a deterministic technical audit against the repository."""
    scope = "FULL"
    if code:
        scope = "CODE"
    elif backend:
        scope = "BACKEND"
    elif frontend:
        scope = "FRONTEND"
    elif security:
        scope = "SECURITY"
    elif e2e:
        scope = "E2E"
    elif full:
        scope = "FULL"

    root = Path(path).resolve()

    async def _run() -> None:
        project = await _ensure_project_registered(root)
        orchestrator = MasterAuditOrchestrator()
        async with AsyncSessionLocal() as db:
            audit_session = AuditSession(
                project_id=project.id,
                status="CREATED",
                current_phase="CREATED",
                audit_scope=scope,
                runner_mode=runner.upper(),
                release_gate="INCOMPLETE_AUDIT",
            )
            db.add(audit_session)
            await db.commit()
            await db.refresh(audit_session)

            completed = await orchestrator.execute_audit_session(
                db=db, session_id=audit_session.id, resume=False
            )
            console.print(
                f"[bold green]Audit Session {completed.id} Completed![/bold green]\n"
                f"Scope: {completed.audit_scope} | Runner: {completed.runner_mode}\n"
                f"Overall Score: {completed.overall_score}/100 | Release Gate: {completed.release_gate}"
            )

    asyncio.run(_run())


@app.command("findings")
def findings_command(
    path: str = typer.Option(".", "--path", "-p", help="Target repository directory"),
    severity: str | None = typer.Option(None, "--severity", help="Filter by severity"),
) -> None:
    """Display findings from the latest audit session."""
    root = Path(path).resolve()

    async def _run() -> None:
        project = await _ensure_project_registered(root)
        async with AsyncSessionLocal() as db:
            latest_session = (
                await db.execute(
                    select(AuditSession)
                    .where(AuditSession.project_id == project.id)
                    .order_by(AuditSession.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest_session is None:
                console.print("[yellow]No audit sessions found for this project.[/yellow]")
                return

            stmt = select(Finding).where(Finding.session_id == latest_session.id)
            if severity:
                stmt = stmt.where(Finding.severity == severity.upper())
            findings = list((await db.execute(stmt)).scalars().all())

            table = Table(title=f"Findings for Session {latest_session.id} ({len(findings)} total)")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Severity", style="magenta")
            table.add_column("Category")
            table.add_column("File:Line")
            table.add_column("Title")
            table.add_column("Status")

            for f in findings:
                table.add_row(
                    str(f.id)[:8],
                    f.severity,
                    f.category,
                    f"{f.file_path or 'global'}:{f.line_start or 1}",
                    f.title,
                    f"{f.verification_status}/{f.lifecycle_status}",
                )
            console.print(table)

    asyncio.run(_run())


@app.command("report")
def report_command(
    path: str = typer.Option(".", "--path", "-p", help="Target repository directory"),
    report_format: str = typer.Option("html", "--format", "-f", help="Report format: html or pdf"),
) -> None:
    """Generate an HTML or PDF technical audit report for the latest audit session."""
    root = Path(path).resolve()

    async def _run() -> None:
        project = await _ensure_project_registered(root)
        async with AsyncSessionLocal() as db:
            latest_session = (
                await db.execute(
                    select(AuditSession)
                    .where(AuditSession.project_id == project.id)
                    .order_by(AuditSession.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest_session is None:
                console.print("[red]No audit session available to report on.[/red]")
                raise typer.Exit(code=1)

            service = ReportService()
            rep = await service.generate_report(
                db=db,
                session_id=latest_session.id,
                report_format=report_format.upper(),
            )
            await db.commit()
            console.print(
                f"[bold green]Generated {rep.report_format} Report:[/bold green] {rep.storage_uri}\n"
                f"SHA-256 Checksum: {rep.sha256_checksum}\n"
                f"Release Recommendation: {rep.release_recommendation}"
            )

    asyncio.run(_run())


@app.command("repair")
def repair_command(
    path: str = typer.Option(".", "--path", "-p", help="Target repository directory"),
    propose: bool = typer.Option(False, "--propose", help="Generate remediation proposals for active findings"),
    approve: str | None = typer.Option(None, "--approve", help="Approve proposal ID"),
    checksum: str | None = typer.Option(None, "--checksum", help="SHA-256 patch checksum for approval"),
    apply_id: str | None = typer.Option(None, "--apply", help="Apply approved proposal ID in isolated branch"),
) -> None:
    """Propose, approve, or apply checksum-verified remediation patches."""
    root = Path(path).resolve()

    async def _run() -> None:
        project = await _ensure_project_registered(root)
        service = RemediationService()
        async with AsyncSessionLocal() as db:
            if propose:
                latest_session = (
                    await db.execute(
                        select(AuditSession)
                        .where(AuditSession.project_id == project.id)
                        .order_by(AuditSession.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if not latest_session:
                    console.print("[red]No audit session found.[/red]")
                    raise typer.Exit(code=1)
                findings = list(
                    (
                        await db.execute(
                            select(Finding)
                            .where(Finding.session_id == latest_session.id)
                            .limit(5)
                        )
                    ).scalars()
                )
                for f in findings:
                    prop = await service.create_proposal(db=db, finding_id=f.id)
                    console.print(
                        f"Proposed Fix ID: [bold cyan]{prop.id}[/bold cyan] | "
                        f"Finding: {f.title} | Checksum: {prop.active_patch_checksum}"
                    )
            elif approve:
                if not checksum:
                    console.print("[red]--checksum is required when approving a proposal.[/red]")
                    raise typer.Exit(code=1)
                prop = await service.approve_proposal(
                    db=db,
                    proposal_id=UUID(approve),
                    patch_checksum=checksum,
                    reviewer_id=None,
                    reviewer_name="CLI Human Reviewer",
                )
                console.print(f"[green]Proposal {prop.id} APPROVED.[/green]")
            elif apply_id:
                prop = await service.apply_approved_patch(db=db, proposal_id=UUID(apply_id))
                console.print(
                    f"[bold green]Proposal {prop.id} Applied & Regression Verified:[/bold green] Status={prop.status}"
                )

    asyncio.run(_run())


@app.command("status")
def status_command(
    path: str = typer.Option(".", "--path", "-p", help="Target repository directory"),
) -> None:
    """Show latest audit session status, quality score, and release gate for the repository."""
    root = Path(path).resolve()

    async def _run() -> None:
        project = await _ensure_project_registered(root)
        async with AsyncSessionLocal() as db:
            latest_session = (
                await db.execute(
                    select(AuditSession)
                    .where(AuditSession.project_id == project.id)
                    .order_by(AuditSession.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest_session is None:
                console.print(f"Project: {project.name} | Status: NO_AUDITS_RUN")
                return
            console.print(
                f"Project: {project.name}\n"
                f"Latest Session: {latest_session.id}\n"
                f"Status: {latest_session.status} (Phase: {latest_session.current_phase})\n"
                f"Tasks: {latest_session.completed_tasks}/{latest_session.total_tasks}\n"
                f"Overall Score: {latest_session.overall_score}/100\n"
                f"Release Gate: {latest_session.release_gate}"
            )

    asyncio.run(_run())


@config_app.command("validate")
def validate_config_command(
    path: str = typer.Option(".", "--path", "-p", help="Target repository directory"),
) -> None:
    """Validate project-level .qc/config.yaml schema."""
    root = Path(path).resolve()
    cfg, cfg_path = load_and_validate_qc_config(root)
    console.print(
        f"[bold green]Configuration Valid![/bold green] Source: {cfg_path or 'defaults'}\n"
        f"Project: {cfg.project.get('name')} | Mode: {cfg.execution.get('mode')} | "
        f"Exclusions: {len(cfg.exclusions)} rule(s)"
    )


if __name__ == "__main__":
    app()
