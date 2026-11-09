"""MasterAuditOrchestrator (AgentService) — DAG task scheduler, state manager, and evidence validator."""

import platform
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.registry.agent_registry import AgentRegistry
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
            # Record snapshot verification log
            snap_info = await runner.verify_snapshot(workspace)
            audit_session.environment_snapshot = {
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
            audit_session.scorecard = scorecard
            audit_session.overall_score = scorecard["overall_score"]
            audit_session.release_gate = scorecard["release_gate"]
            await db.commit()

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
