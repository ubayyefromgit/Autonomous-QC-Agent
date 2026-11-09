"""ReportService — Generates comprehensive 21-section HTML and PDF technical audit reports."""

import html
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.security import compute_sha256_bytes
from backend.app.models.entities import (
    AuditMetric,
    AuditSession,
    AuditTask,
    Evidence,
    Finding,
    Patch,
    Project,
    RegressionRun,
    RemediationProposal,
    Report,
    RepositoryFile,
    TestRun,
)


class ReportService:
    """Produces verifiable 21-section HTML and PDF technical audit reports."""

    def __init__(self, storage_root: Path | None = None) -> None:
        settings = get_settings()
        self.storage_root = (storage_root or settings.storage_path) / "reports"
        self.storage_root.mkdir(parents=True, exist_ok=True)

    async def generate_report(
        self,
        db: AsyncSession,
        session_id: UUID,
        report_format: str = "HTML",
    ) -> Report:
        fmt = report_format.upper()
        audit_session = await db.get(AuditSession, session_id)
        if audit_session is None:
            raise ValueError(f"AuditSession {session_id} not found")

        project = await db.get(Project, audit_session.project_id)
        tasks = list(
            (
                await db.execute(
                    select(AuditTask).where(AuditTask.session_id == session_id)
                )
            ).scalars()
        )
        findings = list(
            (
                await db.execute(
                    select(Finding)
                    .where(Finding.session_id == session_id)
                    .order_by(Finding.created_at.asc())
                )
            ).scalars()
        )
        evidence_items = list(
            (
                await db.execute(
                    select(Evidence).where(Evidence.session_id == session_id)
                )
            ).scalars()
        )
        test_runs = list(
            (
                await db.execute(
                    select(TestRun).where(TestRun.session_id == session_id)
                )
            ).scalars()
        )
        metrics = list(
            (
                await db.execute(
                    select(AuditMetric).where(AuditMetric.session_id == session_id)
                )
            ).scalars()
        )
        repo_files = list(
            (
                await db.execute(
                    select(RepositoryFile)
                    .where(RepositoryFile.session_id == session_id)
                    .limit(300)
                )
            ).scalars()
        )
        proposals = list(
            (
                await db.execute(
                    select(RemediationProposal).where(
                        RemediationProposal.session_id == session_id
                    )
                )
            ).scalars()
        )

        proposal_ids = [p.id for p in proposals]
        patches: list[Patch] = []
        regressions: list[RegressionRun] = []
        if proposal_ids:
            patches = list(
                (
                    await db.execute(
                        select(Patch).where(Patch.proposal_id.in_(proposal_ids))
                    )
                ).scalars()
            )
            patch_ids = [pt.id for pt in patches]
            if patch_ids:
                regressions = list(
                    (
                        await db.execute(
                            select(RegressionRun).where(
                                RegressionRun.patch_id.in_(patch_ids)
                            )
                        )
                    ).scalars()
                )

        scorecard = audit_session.scorecard or {}
        incomplete_checks = scorecard.get("incomplete_tasks", [])
        audit_complete = bool(scorecard.get("audit_complete", False))

        evidence_by_finding: dict[UUID, list[Evidence]] = {}
        for ev in evidence_items:
            if ev.finding_id:
                evidence_by_finding.setdefault(ev.finding_id, []).append(ev)

        if fmt == "PDF":
            raw_bytes = self._render_pdf(
                project=project,
                audit_session=audit_session,
                findings=findings,
                test_runs=test_runs,
                proposals=proposals,
                patches=patches,
                regressions=regressions,
                incomplete_checks=incomplete_checks,
            )
            ext = ".pdf"
        else:
            html_str = self._render_html(
                project=project,
                audit_session=audit_session,
                tasks=tasks,
                findings=findings,
                evidence_by_finding=evidence_by_finding,
                test_runs=test_runs,
                metrics=metrics,
                repo_files=repo_files,
                proposals=proposals,
                patches=patches,
                regressions=regressions,
                incomplete_checks=incomplete_checks,
            )
            raw_bytes = html_str.encode("utf-8")
            ext = ".html"

        checksum = compute_sha256_bytes(raw_bytes)
        report_dir = self.storage_root / str(session_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"qc_audit_report_{checksum[:12]}{ext}"
        report_path.write_bytes(raw_bytes)

        report_entity = Report(
            session_id=session_id,
            report_format=fmt,
            storage_uri=str(report_path),
            sha256_checksum=checksum,
            release_recommendation=audit_session.release_gate,
            overall_score=float(audit_session.overall_score or 0.0),
            audit_complete=audit_complete,
            incomplete_checks=incomplete_checks,
        )
        db.add(report_entity)
        await db.flush()
        return report_entity

    def _render_html(
        self,
        project: Project | None,
        audit_session: AuditSession,
        tasks: list[AuditTask],
        findings: list[Finding],
        evidence_by_finding: dict[UUID, list[Evidence]],
        test_runs: list[TestRun],
        metrics: list[AuditMetric],
        repo_files: list[RepositoryFile],
        proposals: list[RemediationProposal],
        patches: list[Patch],
        regressions: list[RegressionRun],
        incomplete_checks: list[str],
    ) -> str:
        manifest = audit_session.manifest_summary or {}
        coverage = manifest.get("coverage", {})
        scorecard = audit_session.scorecard or {}
        proj_name = html.escape(project.name if project else "Audited Project")

        def _render_findings_list(cat_filter: set[str] | None = None) -> str:
            filtered = [
                f
                for f in findings
                if cat_filter is None or f.category in cat_filter
            ]
            if not filtered:
                return "<p class='empty'>No findings recorded in this category.</p>"
            rows: list[str] = []
            for f in filtered:
                evs = evidence_by_finding.get(f.id, [])
                ev_badges = ", ".join(
                    f"<code>{html.escape(e.evidence_type)} ({e.sha256_checksum[:8]})</code>"
                    for e in evs
                ) or "None"
                rows.append(
                    f"""
                    <div class="finding-card sev-{html.escape(f.severity.lower())}">
                        <div class="finding-header">
                            <span class="badge">{html.escape(f.severity)}</span>
                            <strong>{html.escape(f.title)}</strong>
                            <span class="meta">[{html.escape(f.verification_status)} | {html.escape(f.lifecycle_status)}]</span>
                        </div>
                        <p>{html.escape(f.description)}</p>
                        <div class="meta">
                            File: <code>{html.escape(f.file_path or 'global')}:{f.line_start or 1}</code> |
                            Agent: <code>{html.escape(f.agent_name)}</code> |
                            Fingerprint: <code>{html.escape(f.fingerprint)}</code>
                        </div>
                        <div class="meta">Recommended Fix: {html.escape(f.recommended_fix or 'N/A')}</div>
                        <div class="meta">Supporting Evidence: {ev_badges}</div>
                    </div>
                    """
                )
            return "\n".join(rows)

        dim_rows = "".join(
            f"<tr><td>{html.escape(dim)}</td><td>{info.get('score', 0)}</td><td>{int(info.get('weight', 0)*100)}%</td><td>{info.get('weighted_score', 0)}</td><td>{info.get('active_findings', 0)}</td></tr>"
            for dim, info in scorecard.get("dimensions", {}).items()
        )

        file_rows = "".join(
            f"<tr><td><code>{html.escape(rf.relative_path)}</code></td><td>{html.escape(rf.language)}</td><td>{html.escape(rf.component_boundary)}</td><td>{html.escape(rf.inspection_status)}</td><td>{html.escape(rf.status_reason or '-')}</td></tr>"
            for rf in repo_files[:60]
        )

        test_rows = "".join(
            f"<tr><td>{html.escape(tr.test_suite_type)}</td><td>{html.escape(tr.tool_name)}</td><td><code>{html.escape(tr.command)}</code></td><td>{html.escape(tr.status)}</td><td>{tr.passed_tests}/{tr.total_tests}</td><td>{tr.duration_seconds}s</td></tr>"
            for tr in test_runs
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>QC Technical Audit Report — {proj_name}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 32px; line-height: 1.5; }}
.container {{ max-width: 1200px; margin: 0 auto; background: #1e293b; padding: 32px; border-radius: 12px; border: 1px solid #334155; }}
h1, h2, h3 {{ color: #f8fafc; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
.grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
.stat {{ background: #0f172a; padding: 16px; border-radius: 8px; border: 1px solid #334155; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 14px; }}
th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #334155; }}
th {{ background: #0f172a; color: #94a3b8; }}
.finding-card {{ background: #0f172a; padding: 16px; border-radius: 8px; margin-bottom: 12px; border-left: 4px solid #64748b; }}
.sev-critical {{ border-left-color: #ef4444; }}
.sev-high {{ border-left-color: #f97316; }}
.sev-medium {{ border-left-color: #eab308; }}
.sev-low {{ border-left-color: #3b82f6; }}
.badge {{ padding: 2px 8px; border-radius: 4px; background: #334155; font-size: 12px; margin-right: 8px; }}
.meta {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
code {{ background: #020617; padding: 2px 6px; border-radius: 4px; color: #38bdf8; }}
</style>
</head>
<body>
<div class="container">
    <h1>Autonomous QC &amp; Project Audit Intelligence Report</h1>
    <section id="sec-1"><h2>1. Executive Summary</h2>
        <div class="grid">
            <div class="stat"><div>Release Gate</div><strong>{html.escape(audit_session.release_gate)}</strong></div>
            <div class="stat"><div>Overall Score</div><strong>{audit_session.overall_score or 0.0} / 100</strong></div>
            <div class="stat"><div>Total Findings</div><strong>{len(findings)}</strong></div>
            <div class="stat"><div>Audit Complete</div><strong>{'YES' if not incomplete_checks else 'INCOMPLETE'}</strong></div>
        </div>
    </section>
    <section id="sec-2"><h2>2. Project Overview</h2>
        <p>Project: <strong>{proj_name}</strong> | Root Path: <code>{html.escape(project.root_path if project else '')}</code> | Session ID: <code>{audit_session.id}</code> | Commit: <code>{html.escape(audit_session.commit_hash or 'snapshot')}</code></p>
    </section>
    <section id="sec-3"><h2>3. Technology Stack</h2>
        <p>Languages: <code>{html.escape(', '.join(manifest.get('languages', [])))}</code> | Frameworks: <code>{html.escape(', '.join(manifest.get('frameworks', [])))}</code> | Databases: <code>{html.escape(', '.join(manifest.get('databases', [])))}</code></p>
    </section>
    <section id="sec-4"><h2>4. Repository Inventory</h2>
        <table><thead><tr><th>File Path</th><th>Language</th><th>Boundary</th><th>Inspection Status</th><th>Reason</th></tr></thead><tbody>{file_rows}</tbody></table>
    </section>
    <section id="sec-5"><h2>5. Inspection Coverage</h2>
        <p>Discovered: <strong>{coverage.get('files_discovered', 0)}</strong> | In Scope: <strong>{coverage.get('files_in_scope', 0)}</strong> | Inspected: <strong>{coverage.get('files_inspected', 0)}</strong> | Excluded: <strong>{coverage.get('files_excluded', 0)}</strong> | Failed: <strong>{coverage.get('files_failed', 0)}</strong> | Coverage: <strong>{coverage.get('inspection_coverage_percent', 0)}%</strong></p>
    </section>
    <section id="sec-6"><h2>6. Architecture Findings</h2>{_render_findings_list({'ARCHITECTURE_VIOLATION', 'CIRCULAR_DEPENDENCY'})}</section>
    <section id="sec-7"><h2>7. Code Quality Findings</h2>{_render_findings_list({'SYNTAX_ERROR', 'LOGIC_DEFECT', 'DEAD_CODE', 'DUPLICATE_CODE', 'EXCEPTION_HANDLING', 'TYPE_ERROR', 'COMPLEXITY', 'INCOMPLETE_IMPLEMENTATION'})}</section>
    <section id="sec-8"><h2>8. Backend Results</h2>{_render_findings_list({'BACKEND_RUNTIME_ERROR', 'API_CONTRACT_FAILURE'})}</section>
    <section id="sec-9"><h2>9. Frontend Results</h2>{_render_findings_list({'FRONTEND_UI_DEFECT', 'BROWSER_CONSOLE_ERROR', 'NETWORK_FAILURE'})}</section>
    <section id="sec-10"><h2>10. API Testing</h2><p>API probe runs executed: {len([t for t in test_runs if t.test_suite_type == 'API'])}</p></section>
    <section id="sec-11"><h2>11. E2E Testing</h2><p>Browser/Integration E2E runs: {len([t for t in test_runs if t.test_suite_type in ('BROWSER_E2E', 'INTEGRATION')])}</p></section>
    <section id="sec-12"><h2>12. Database Assessment</h2>{_render_findings_list({'DATABASE_INTEGRITY', 'MIGRATION_DEFECT'})}</section>
    <section id="sec-13"><h2>13. Security Findings</h2>{_render_findings_list({'SECURITY_VULNERABILITY', 'SECRET_EXPOSURE'})}</section>
    <section id="sec-14"><h2>14. Performance Findings</h2>{_render_findings_list({'PERFORMANCE_BOTTLENECK'})}</section>
    <section id="sec-15"><h2>15. Dependency Findings</h2>{_render_findings_list({'DEPENDENCY_VULNERABILITY'})}</section>
    <section id="sec-16"><h2>16. Deterministic Test Execution Results</h2>
        <table><thead><tr><th>Suite</th><th>Tool</th><th>Command</th><th>Status</th><th>Passed/Total</th><th>Duration</th></tr></thead><tbody>{test_rows}</tbody></table>
    </section>
    <section id="sec-17"><h2>17. Incomplete Checks</h2><p>{html.escape(', '.join(incomplete_checks) if incomplete_checks else 'All scheduled tasks in scope completed.')}</p></section>
    <section id="sec-18"><h2>18. Proposed Remediations</h2><p>Remediation Proposals Generated: <strong>{len(proposals)}</strong></p></section>
    <section id="sec-19"><h2>19. Applied Fixes</h2><p>Approved Patches Applied: <strong>{len([p for p in patches if p.applied_at is not None])}</strong></p></section>
    <section id="sec-20"><h2>20. Regression Verification Results</h2><p>Regression Runs Executed: <strong>{len(regressions)}</strong> (Verified Resolved: {len([r for r in regressions if r.issue_resolved])})</p></section>
    <section id="sec-21"><h2>21. Scorecard &amp; Release Recommendation</h2>
        <table><thead><tr><th>Dimension</th><th>Score</th><th>Weight</th><th>Weighted</th><th>Active Findings</th></tr></thead><tbody>{dim_rows}</tbody></table>
        <p>Final Release Gate Recommendation: <strong>{html.escape(audit_session.release_gate)}</strong></p>
        <p>Blocking Conditions: {html.escape('; '.join(scorecard.get('blocking_reasons', [])) or 'None')}</p>
    </section>
</div>
</body>
</html>"""

    def _render_pdf(
        self,
        project: Project | None,
        audit_session: AuditSession,
        findings: list[Finding],
        test_runs: list[TestRun],
        proposals: list[RemediationProposal],
        patches: list[Patch],
        regressions: list[RegressionRun],
        incomplete_checks: list[str],
    ) -> bytes:
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        styles = getSampleStyleSheet()
        story: list[Any] = []

        proj_name = project.name if project else "Audited Project"
        story.append(Paragraph(f"Autonomous QC Technical Audit Report — {proj_name}", styles["Title"]))
        story.append(Spacer(1, 12))
        story.append(
            Paragraph(
                f"Session ID: {audit_session.id} | Release Gate: {audit_session.release_gate} | "
                f"Score: {audit_session.overall_score or 0.0}/100 | Generated: {datetime.now(UTC).isoformat()}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 12))

        summary_data = [
            ["Metric", "Value"],
            ["Project Name", proj_name],
            ["Audit Scope", audit_session.audit_scope],
            ["Runner Mode", audit_session.runner_mode],
            ["Total Findings", str(len(findings))],
            ["Test Suites Run", str(len(test_runs))],
            ["Remediation Proposals", str(len(proposals))],
            ["Applied Patches", str(len([p for p in patches if p.applied_at]))],
            ["Regression Runs", str(len(regressions))],
            ["Incomplete Checks", ", ".join(incomplete_checks) if incomplete_checks else "None"],
        ]
        tbl = Table(summary_data, colWidths=[180, 320])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("PADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(tbl)
        story.append(Spacer(1, 16))
        story.append(Paragraph("Confirmed & Suspected Findings", styles["Heading2"]))

        for f in findings[:50]:
            story.append(
                Paragraph(
                    f"<b>[{f.severity}] {html.escape(f.title)}</b> ({f.file_path or 'global'}:{f.line_start or 1}) — "
                    f"Status: {f.verification_status} / {f.lifecycle_status}",
                    styles["Normal"],
                )
            )
            story.append(Spacer(1, 6))

        doc.build(story)
        return buf.getvalue()
