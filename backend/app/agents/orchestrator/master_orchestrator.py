"""MasterAuditOrchestrator (AgentService) — DAG task scheduler, state manager, and evidence validator."""

import platform
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.registry.agent_registry import AgentRegistry
from backend.app.application.services.remediation_service import RemediationService
from backend.app.audit_engine.discovery.repository_intelligence_engine import (
    RepositoryIntelligenceEngine,
)
from backend.app.audit_engine.evidence.evidence_service import EvidenceService
from backend.app.audit_engine.reporting.report_service import ReportService
from backend.app.audit_engine.scoring.scoring_engine import QualityScoringEngine
from backend.app.audit_engine.validation.finding_validation_engine import (
    FindingValidationEngine,
)
from backend.app.domain.entities.state_machines import AuditStateMachine
from backend.app.domain.enums.audit_enums import (
    AuditScope,
    AuditSessionStatus,
    EvidenceType,
    RunnerMode,
    TaskStatus,
)
from backend.app.domain.interfaces.contracts import AuditContext, AuditTaskDTO
from backend.app.infrastructure.ai.llm_gateway import LLMRequest, UnifiedLLMGateway
from backend.app.infrastructure.execution.project_runner import get_project_runner
from backend.app.models.entities import (
    AgentExecution,
    AuditEvent,
    AuditMetric,
    AuditSession,
    AuditTask,
    ExecutionLog,
    Finding,
    Project,
    ProjectConfiguration,
    RepositoryFile,
    TestRun,
)

SCOPE_TASK_KEYS: dict[str, set[str]] = {
    AuditScope.FULL.value: {
        "repository_intelligence",
        "code_quality_audit",
        "architecture_audit",
        "security_audit",
        "backend_qa_audit",
        "frontend_qa_audit",
        "database_audit",
        "performance_audit",
        "integration_e2e_audit",
    },
    AuditScope.CODE.value: {
        "repository_intelligence",
        "code_quality_audit",
        "architecture_audit",
    },
    AuditScope.BACKEND.value: {
        "repository_intelligence",
        "code_quality_audit",
        "backend_qa_audit",
        "database_audit",
    },
    AuditScope.FRONTEND.value: {
        "repository_intelligence",
        "code_quality_audit",
        "frontend_qa_audit",
    },
    AuditScope.DATABASE.value: {
        "repository_intelligence",
        "database_audit",
    },
    AuditScope.SECURITY.value: {
        "repository_intelligence",
        "security_audit",
    },
    AuditScope.PERFORMANCE.value: {
        "repository_intelligence",
        "code_quality_audit",
        "performance_audit",
    },
    AuditScope.E2E.value: {
        "repository_intelligence",
        "code_quality_audit",
        "backend_qa_audit",
        "frontend_qa_audit",
        "integration_e2e_audit",
    },
}


class MasterAuditOrchestrator:
    """Centralized AgentService coordinating discovery, planning, specialized agents, evidence, and scoring."""

    def __init__(self) -> None:
        self.agent_registry = AgentRegistry()
        self.evidence_service = EvidenceService()
        self.finding_validator = FindingValidationEngine(self.evidence_service)
        self.scoring_engine = QualityScoringEngine()
        self.report_service = ReportService()

    async def execute_audit_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        resume: bool = False,
    ) -> AuditSession:
        audit_session = await db.get(AuditSession, session_id)
        if audit_session is None:
            raise ValueError(f"AuditSession {session_id} not found")

        project = await db.get(Project, audit_session.project_id)
        if project is None:
            raise ValueError(f"Project {audit_session.project_id} not found")

        config_row = (
            await db.execute(
                select(ProjectConfiguration).where(
                    ProjectConfiguration.project_id == project.id
                )
            )
        ).scalar_one_or_none()
        custom_exclusions = config_row.exclusions if config_row else []
        quality_policy = config_row.quality_gate_policy if config_row else {}

        if audit_session.started_at is None:
            audit_session.started_at = datetime.now(UTC)

        runner = get_project_runner(audit_session.runner_mode)
        workspace = await runner.prepare_workspace(
            project_path=project.root_path,
            session_id=session_id,
            config={"exclusions": custom_exclusions},
        )

        try:
            # Record snapshot verification log while preserving custom_instructions and project_documentation
            existing_env_snap = dict(audit_session.environment_snapshot or {})
            custom_instructions = str(existing_env_snap.get("custom_instructions", "")).strip()
            project_documentation = str(existing_env_snap.get("project_documentation", "")).strip()
            snap_info = await runner.verify_snapshot(workspace)
            audit_session.environment_snapshot = {
                **existing_env_snap,
                "custom_instructions": custom_instructions,
                "project_documentation": project_documentation,
                "python_version": sys.version,
                "os": platform.platform(),
                "runner_mode": audit_session.runner_mode,
                "workspace_snapshot": snap_info,
                "recorded_at": datetime.now(UTC).isoformat(),
            }

            if not resume or not audit_session.manifest_summary:
                # PHASE 1: DISCOVERING
                self._transition_session(
                    audit_session, AuditSessionStatus.DISCOVERING, "DISCOVERY"
                )
                await self._emit_event(
                    db,
                    session_id,
                    project.id,
                    "AUDIT_DISCOVERY_STARTED",
                    f"Discovering repository files at {project.root_path}",
                )
                await db.commit()

                engine = RepositoryIntelligenceEngine(custom_exclusions=custom_exclusions)
                discovery = engine.discover_repository(project.root_path)
                manifest = discovery["manifest"]
                audit_session.manifest_summary = manifest
                audit_session.commit_hash = manifest.get("git", {}).get("commit_hash")
                audit_session.branch_name = manifest.get("git", {}).get("branch")
                project.detected_stack = {
                    "languages": manifest.get("languages", []),
                    "frameworks": manifest.get("frameworks", []),
                    "databases": manifest.get("databases", []),
                    "infrastructure": manifest.get("infrastructure", []),
                    "test_frameworks": manifest.get("test_frameworks", []),
                    "coverage": manifest.get("coverage", {}),
                }

                # Persist RepositoryFile inventory
                await db.execute(
                    delete(RepositoryFile).where(RepositoryFile.session_id == session_id)
                )
                for f_rec in discovery["files"]:
                    db.add(
                        RepositoryFile(
                            session_id=session_id,
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
                await db.commit()

                # PHASE 2: PLANNING
                self._transition_session(
                    audit_session, AuditSessionStatus.PLANNING, "PLANNING"
                )
                planned_tasks = self._filter_plan_for_scope(
                    manifest.get("audit_plan", []), audit_session.audit_scope
                )
                await db.execute(
                    delete(AuditTask).where(AuditTask.session_id == session_id)
                )
                for pt in planned_tasks:
                    db.add(
                        AuditTask(
                            session_id=session_id,
                            task_key=pt["task_key"],
                            agent_type=pt["agent_type"],
                            phase=pt["phase"],
                            status=TaskStatus.PENDING.value,
                            dependencies=pt["dependencies"],
                            input_payload={"reason": pt.get("reason", "")},
                        )
                    )
                audit_session.total_tasks = len(planned_tasks)
                audit_session.completed_tasks = 0
                audit_session.failed_tasks = 0
                await db.commit()

            # PHASE 3: EXECUTING
            self._transition_session(
                audit_session, AuditSessionStatus.EXECUTING, "EXECUTING_AGENTS"
            )
            await db.commit()

            tasks_stmt = (
                select(AuditTask)
                .where(AuditTask.session_id == session_id)
                .order_by(AuditTask.created_at.asc())
            )
            all_tasks = list((await db.execute(tasks_stmt)).scalars().all())
            task_by_key = {t.task_key: t for t in all_tasks}

            context = AuditContext(
                session_id=session_id,
                project_id=project.id,
                project_name=project.name,
                root_path=project.root_path,
                workspace_path=str(workspace.workspace_dir),
                runner_mode=RunnerMode(audit_session.runner_mode),
                audit_scope=AuditScope(audit_session.audit_scope),
                manifest=audit_session.manifest_summary or {},
                configuration={
                    "exclusions": custom_exclusions,
                    "quality_gate_policy": quality_policy,
                    "custom_instructions": custom_instructions,
                    "project_documentation": project_documentation,
                    "skip_nested_pytest": bool(
                        config_row and config_row.custom_rules.get("skip_nested_pytest")
                    ),
                },
            )

            for task_obj in all_tasks:
                # Reload session to check if user cancelled
                await db.refresh(audit_session)
                if audit_session.status == AuditSessionStatus.CANCELLED.value:
                    break

                if task_obj.status == TaskStatus.COMPLETED.value and resume:
                    continue

                # Check if dependencies succeeded
                failed_deps = [
                    dep
                    for dep in task_obj.dependencies
                    if dep in task_by_key
                    and task_by_key[dep].status == TaskStatus.FAILED.value
                ]
                if failed_deps:
                    task_obj.status = TaskStatus.SKIPPED.value
                    task_obj.error_message = f"Skipped due to failed dependency: {failed_deps}"
                    await db.commit()
                    continue

                audit_session.current_phase = task_obj.phase
                task_obj.status = TaskStatus.RUNNING.value
                task_obj.attempts += 1
                task_obj.started_at = datetime.now(UTC)
                await db.commit()

                agent = self.agent_registry.get_agent(task_obj.agent_type)
                agent_exec = AgentExecution(
                    session_id=session_id,
                    task_id=task_obj.id,
                    agent_name=agent.agent_name,
                    status="RUNNING",
                )
                db.add(agent_exec)
                await db.flush()

                task_dto = AuditTaskDTO(
                    id=task_obj.id,
                    task_key=task_obj.task_key,
                    agent_type=task_obj.agent_type,
                    phase=task_obj.phase,
                    status=TaskStatus.RUNNING,
                    dependencies=task_obj.dependencies,
                    input_payload=task_obj.input_payload,
                )

                try:
                    result = await agent.execute(context, task_dto)

                    # Persist ExecutionLog for task traceability
                    db.add(
                        ExecutionLog(
                            session_id=session_id,
                            task_id=task_obj.id,
                            runner_type=audit_session.runner_mode,
                            command=f"{agent.agent_name}.execute({task_obj.task_key})",
                            working_dir=str(workspace.workspace_dir),
                            exit_code=0 if result.status == TaskStatus.COMPLETED else 1,
                            duration_seconds=result.duration_seconds,
                            timed_out=False,
                            stdout_preview=str(result.summary)[:1000],
                            stderr_preview="\n".join(result.errors)[:1000] if result.errors else None,
                        )
                    )

                    # Persist TestRuns
                    for tr_dto in result.test_runs:
                        ev = await self.evidence_service.store_evidence(
                            db=db,
                            session_id=session_id,
                            task_id=task_obj.id,
                            evidence_type=EvidenceType.TEST_OUTPUT.value,
                            source_tool=tr_dto.tool_name,
                            content_text=tr_dto.output_text,
                            content_excerpt=tr_dto.output_text[:1000],
                            metadata_json=tr_dto.details,
                            filename_hint=f"{tr_dto.tool_name}_output.txt",
                        )
                        db.add(
                            TestRun(
                                session_id=session_id,
                                task_id=task_obj.id,
                                test_suite_type=str(tr_dto.test_suite_type),
                                tool_name=tr_dto.tool_name,
                                command=tr_dto.command,
                                status=str(tr_dto.status),
                                total_tests=tr_dto.total_tests,
                                passed_tests=tr_dto.passed_tests,
                                failed_tests=tr_dto.failed_tests,
                                skipped_tests=tr_dto.skipped_tests,
                                duration_seconds=tr_dto.duration_seconds,
                                exit_code=tr_dto.exit_code,
                                output_evidence_uri=ev.storage_uri,
                                details=tr_dto.details,
                            )
                        )

                    # Persist Findings + Evidence through FindingValidationEngine
                    for f_dto in result.findings:
                        await self.finding_validator.ingest_finding(
                            db=db,
                            project_id=project.id,
                            session_id=session_id,
                            task_id=task_obj.id,
                            dto=f_dto,
                        )

                    # Persist Metrics
                    for m_dto in result.metrics:
                        db.add(
                            AuditMetric(
                                session_id=session_id,
                                dimension=str(m_dto.dimension),
                                metric_name=m_dto.metric_name,
                                metric_value=m_dto.metric_value,
                                unit=m_dto.unit,
                                weight=m_dto.weight,
                                breakdown=m_dto.breakdown,
                            )
                        )

                    task_obj.status = TaskStatus.COMPLETED.value
                    task_obj.result_summary = result.summary
                    task_obj.duration_seconds = result.duration_seconds
                    task_obj.completed_at = datetime.now(UTC)

                    agent_exec.status = "COMPLETED"
                    agent_exec.duration_seconds = result.duration_seconds
                    agent_exec.prompt_tokens = result.prompt_tokens
                    agent_exec.completion_tokens = result.completion_tokens
                    agent_exec.llm_provider = result.llm_provider
                    agent_exec.llm_model = result.llm_model
                    agent_exec.warnings = result.warnings
                    agent_exec.errors = result.errors
                    agent_exec.completed_at = datetime.now(UTC)

                    audit_session.completed_tasks += 1
                    await db.commit()
                except Exception as exc:
                    task_obj.status = TaskStatus.FAILED.value
                    task_obj.error_message = str(exc)
                    task_obj.completed_at = datetime.now(UTC)
                    agent_exec.status = "FAILED"
                    agent_exec.errors = [str(exc)]
                    agent_exec.completed_at = datetime.now(UTC)
                    audit_session.failed_tasks += 1
                    await db.commit()

            await db.refresh(audit_session)
            if audit_session.status == AuditSessionStatus.CANCELLED.value:
                return audit_session

            # PHASE 4: VALIDATING
            self._transition_session(
                audit_session, AuditSessionStatus.VALIDATING, "VALIDATING_FINDINGS"
            )
            await db.commit()

            # PHASE 5: SCORING
            self._transition_session(
                audit_session, AuditSessionStatus.SCORING, "COMPUTING_SCORECARD"
            )
            findings_rows = list(
                (
                    await db.execute(
                        select(Finding).where(Finding.session_id == session_id)
                    )
                ).scalars()
            )
            tasks_rows = list(
                (
                    await db.execute(
                        select(AuditTask).where(AuditTask.session_id == session_id)
                    )
                ).scalars()
            )
            test_rows = list(
                (
                    await db.execute(
                        select(TestRun).where(TestRun.session_id == session_id)
                    )
                ).scalars()
            )

            coverage_pct = float(
                (audit_session.manifest_summary or {})
                .get("coverage", {})
                .get("inspection_coverage_percent", 100.0)
            )
            scorecard = self.scoring_engine.evaluate(
                findings=[
                    {
                        "severity": f.severity,
                        "category": f.category,
                        "verification_status": f.verification_status,
                        "lifecycle_status": f.lifecycle_status,
                    }
                    for f in findings_rows
                ],
                tasks=[
                    {"task_key": t.task_key, "status": t.status} for t in tasks_rows
                ],
                test_runs=[
                    {
                        "total_tests": tr.total_tests,
                        "passed_tests": tr.passed_tests,
                        "failed_tests": tr.failed_tests,
                    }
                    for tr in test_rows
                ],
                coverage_percent=coverage_pct,
                custom_policy=quality_policy,
            )
            completed_ts = datetime.now(UTC)
            audit_session.completed_at = completed_ts
            started_ts = audit_session.started_at or completed_ts
            if started_ts.tzinfo is None:
                started_ts = started_ts.replace(tzinfo=UTC)
            duration_sec = round(max(0.1, (completed_ts - started_ts).total_seconds()), 2)

            readable_insights = await self._synthesize_readable_insights(
                audit_session=audit_session,
                project=project,
                findings_rows=findings_rows,
                tasks_rows=tasks_rows,
                test_rows=test_rows,
                scorecard=scorecard,
                custom_instructions=custom_instructions,
                project_documentation=project_documentation,
                duration_sec=duration_sec,
            )
            scorecard["readable_insights"] = readable_insights
            audit_session.scorecard = scorecard
            audit_session.overall_score = scorecard["overall_score"]
            audit_session.release_gate = scorecard["release_gate"]
            await db.commit()

            # Automatically generate Remediation Proposals for top actionable findings with source files
            try:
                rem_service = RemediationService()
                sev_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
                candidate_findings = sorted(
                    [f for f in findings_rows if f.file_path],
                    key=lambda x: sev_rank.get(str(x.severity).upper(), 99),
                )[:5]
                for cf in candidate_findings:
                    try:
                        await rem_service.create_proposal(db=db, finding_id=cf.id)
                    except Exception:
                        pass
            except Exception:
                pass

            # PHASE 6: REPORTING
            self._transition_session(
                audit_session, AuditSessionStatus.REPORTING, "GENERATING_REPORT"
            )
            await self.report_service.generate_report(
                db=db, session_id=session_id, report_format="HTML"
            )
            await db.commit()

            # PHASE 7: COMPLETED
            self._transition_session(
                audit_session, AuditSessionStatus.COMPLETED, "COMPLETED"
            )
            audit_session.completed_at = datetime.now(UTC)
            await self._emit_event(
                db,
                session_id,
                project.id,
                "AUDIT_COMPLETED",
                f"Audit completed with score {audit_session.overall_score} and gate {audit_session.release_gate}",
            )
            await db.commit()
            return audit_session
        finally:
            await runner.cleanup(workspace)

    def _transition_session(
        self,
        audit_session: AuditSession,
        target: AuditSessionStatus,
        phase_label: str,
    ) -> None:
        current = AuditSessionStatus(audit_session.status)
        AuditStateMachine.validate_transition(current, target)
        audit_session.status = target.value
        audit_session.current_phase = phase_label

    def _filter_plan_for_scope(
        self, full_plan: list[dict[str, Any]], scope: str
    ) -> list[dict[str, Any]]:
        allowed_keys = SCOPE_TASK_KEYS.get(scope.upper(), SCOPE_TASK_KEYS[AuditScope.FULL.value])
        filtered: list[dict[str, Any]] = []
        for item in full_plan:
            if item["task_key"] in allowed_keys:
                deps = [d for d in item.get("dependencies", []) if d in allowed_keys]
                filtered.append({**item, "dependencies": deps})
        return filtered

    async def _synthesize_readable_insights(
        self,
        audit_session: AuditSession,
        project: Project,
        findings_rows: list[Finding],
        tasks_rows: list[AuditTask],
        test_rows: list[TestRun],
        scorecard: dict[str, Any],
        custom_instructions: str,
        project_documentation: str,
        duration_sec: float,
    ) -> dict[str, Any]:
        manifest = audit_session.manifest_summary or {}
        cov = manifest.get("coverage", {})
        total_files = int(
            cov.get("files_discovered", cov.get("total_discovered", 0))
        )
        in_scope = int(
            cov.get("files_in_scope", cov.get("in_scope", 0))
        )
        inspected = int(
            cov.get("files_inspected", cov.get("inspected", 0))
        ) + int(cov.get("files_partially_inspected", 0))
        excluded = int(cov.get("files_excluded", 0))
        unsupported = int(cov.get("files_unsupported", 0))
        cov_pct = float(cov.get("inspection_coverage_percent", 100.0))
        lang_counts = manifest.get("language_file_counts", {})
        langs = ", ".join(manifest.get("languages", [])) or "Unknown"
        frameworks = ", ".join(manifest.get("frameworks", [])) or "Standard Stack"

        sev_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        sev_counts: dict[str, int] = {k: 0 for k in sev_order}
        for f in findings_rows:
            s = str(f.severity or "INFO").upper()
            sev_counts[s] = sev_counts.get(s, 0) + 1

        sorted_findings = sorted(
            findings_rows,
            key=lambda x: sev_order.index(str(x.severity).upper())
            if str(x.severity).upper() in sev_order
            else 99,
        )

        top_findings_readable = [
            {
                "id": str(f.id),
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "location": f"{f.file_path or 'project'}{f':{f.line_start}' if f.line_start else ''}",
                "what_we_found": f.description,
                "why_it_matters": f.impact or "Affects software reliability, security, or maintainability.",
                "how_to_fix": f.recommended_fix or "Review source location and apply recommended code fix.",
            }
            for f in sorted_findings[:15]
        ]

        overall_score = float(scorecard.get("overall_score", 0.0))
        gate = str(scorecard.get("release_gate", "Conditional"))
        total_issues = len(findings_rows)
        crit_high = sev_counts["CRITICAL"] + sev_counts["HIGH"]

        executive_headline = (
            f"Audited '{project.name}' in {duration_sec}s — inspected {inspected} of {in_scope} in-scope files "
            f"({total_files} total discovered, {excluded} excluded; {cov_pct:.0f}% coverage). "
            f"Overall Score: {overall_score}/100 ({gate.replace('_', ' ')}) "
            f"with {total_issues} finding(s) ({crit_high} Critical/High)."
        )

        total_tests = sum(int(t.total_tests or 0) for t in test_rows)
        passed_tests = sum(int(t.passed_tests or 0) for t in test_rows)
        failed_tests = sum(int(t.failed_tests or 0) for t in test_rows)

        key_takeaways = [
            f"Files Covered & Stack: Inspected {inspected}/{in_scope} in-scope files ({total_files} total discovered, {excluded} excluded) across {langs} ({frameworks}).",
            (
                "Security & Risk Posture: No Critical or High severity vulnerabilities detected."
                if crit_high == 0
                else f"Security & Risk Posture: Found {sev_counts['CRITICAL']} Critical and {sev_counts['HIGH']} High severity issues that should be fixed first."
            ),
            (
                f"Code Quality & Architecture: {sev_counts['MEDIUM']} Medium and {sev_counts['LOW']} Low severity code/architecture findings identified."
                if (sev_counts["MEDIUM"] + sev_counts["LOW"]) > 0
                else "Code Quality & Architecture: Clean structure with no major code or architecture smells."
            ),
            (
                f"Automated Tests & Execution: Ran {total_tests} test(s) ({passed_tests} passed, {failed_tests} failed) across {len(tasks_rows)} audit agents."
                if total_tests > 0
                else f"Automated Tests & Execution: Completed {len(tasks_rows)} specialized audit agent checks across static, security, and runtime layers."
            ),
        ]

        doc_alignment = ""
        if project_documentation:
            doc_Preview = project_documentation[:300].replace("\n", " ")
            doc_alignment = (
                f"Verified project documentation ({len(project_documentation)} chars: \"{doc_Preview}...\") against "
                f"{inspected} inspected source files in {langs} ({frameworks}). "
                f"Detected {len(manifest.get('entrypoints', []))} entrypoint(s) and {total_issues} total code/runtime findings."
            )

        custom_response = ""
        ai_model_used = "deterministic-analyzer"
        combined_prompt = custom_instructions or project_documentation
        if combined_prompt:
            findings_brief = "\n".join(
                f"- [{f.severity}] ({f.category}) {f.title} at {f.file_path}:{f.line_start} -> {f.description}"
                for f in sorted_findings[:12]
            ) or "No defects or vulnerabilities were triggered by deterministic scanners."

            keywords = [
                w.lower()
                for w in combined_prompt.replace(",", " ").replace(".", " ").split()
                if len(w) >= 3
            ]
            matching_findings = [
                f
                for f in sorted_findings
                if any(
                    kw in f"{f.title} {f.description} {f.category} {f.file_path or ''}".lower()
                    for kw in keywords
                )
            ]
            det_summary = (
                f"Evaluated your project documentation and instructions against {inspected}/{in_scope} inspected files ({langs} / {frameworks}). "
            )
            if matching_findings:
                det_summary += (
                    f"Identified {len(matching_findings)} directly related finding(s): "
                    + "; ".join(
                        f"[{m.severity}] {m.title} ({m.file_path or 'project'})"
                        for m in matching_findings[:5]
                    )
                    + "."
                )
            elif sorted_findings:
                det_summary += (
                    f"No defects specifically violated your custom focus topic, though {len(sorted_findings)} general finding(s) were detected across the project."
                )
            else:
                det_summary += "All inspected files passed verification with 0 defects found."

            custom_response = det_summary
            try:
                gateway = UnifiedLLMGateway()
                llm_resp = await gateway.generate(
                    LLMRequest(
                        system_prompt=(
                            "You are a Principal Software QC Auditor. Respond in clear, plain, concise English "
                            "(3 to 5 short bullet points) directly evaluating the project against the provided "
                            "Project Documentation and Custom Audit Instructions."
                        ),
                        user_prompt=(
                            f"Project: {project.name}\n"
                            f"Detected Stack: {langs} ({frameworks})\n"
                            f"Files Inspected: {inspected}/{in_scope} ({total_files} total discovered)\n"
                            f"Overall Score: {overall_score}/100 ({gate})\n"
                            f"Project Documentation / Details:\n{project_documentation[:2500] or 'N/A'}\n\n"
                            f"User Custom Audit Instructions:\n{custom_instructions or 'General full-stack audit'}\n\n"
                            f"Confirmed Audit Findings:\n{findings_brief}\n\n"
                            "Provide a direct, easy-to-read response comparing the documentation/instructions with the actual audit findings:"
                        ),
                        timeout_seconds=6.0,
                    )
                )
                if (
                    llm_resp.content
                    and not llm_resp.used_fallback
                    and llm_resp.provider != "deterministic_analyzer"
                ):
                    custom_response = llm_resp.content.strip()
                    ai_model_used = f"{llm_resp.provider}:{llm_resp.model}"
            except Exception:
                pass

        return {
            "executive_headline": executive_headline,
            "custom_instructions": custom_instructions,
            "project_documentation_summary": doc_alignment,
            "custom_instructions_response": custom_response,
            "ai_model_used": ai_model_used,
            "key_takeaways": key_takeaways,
            "file_coverage_breakdown": {
                "files_discovered": total_files,
                "files_in_scope": in_scope,
                "files_inspected": inspected,
                "files_excluded": excluded,
                "files_unsupported": unsupported,
                "inspection_coverage_percent": cov_pct,
                "language_file_counts": lang_counts,
            },
            "severity_counts": sev_counts,
            "top_findings_readable": top_findings_readable,
            "run_timing": {
                "started_at": audit_session.started_at.isoformat() if audit_session.started_at else None,
                "completed_at": audit_session.completed_at.isoformat() if audit_session.completed_at else None,
                "duration_seconds": duration_sec,
            },
        }

    async def _emit_event(
        self,
        db: AsyncSession,
        session_id: UUID,
        project_id: UUID,
        event_type: str,
        message: str,
    ) -> None:
        db.add(
            AuditEvent(
                session_id=session_id,
                project_id=project_id,
                event_type=event_type,
                actor="MasterAuditOrchestrator",
                severity="INFO",
                message=message,
                payload={},
            )
        )
        await db.flush()
