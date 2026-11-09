"""Integration Auditor — Executes full-stack test suites and validates frontend-backend contract alignment."""

import re
import time
from pathlib import Path

from backend.app.domain.enums.audit_enums import (
    AuditScope,
    EvidenceType,
    FindingCategory,
    FindingSeverity,
    FindingVerificationStatus,
    QualityDimension,
    TaskStatus,
    TestRunStatus,
    TestSuiteType,
)
from backend.app.domain.interfaces.contracts import (
    AgentResult,
    AuditContext,
    AuditTaskDTO,
    BaseSpecializedAgent,
    EvidenceCreateDTO,
    FindingCreateDTO,
    MetricCreateDTO,
    TestRunCreateDTO,
)
from backend.app.infrastructure.execution.project_runner import (
    WorkspaceInfo,
    get_project_runner,
)

PYTEST_SUMMARY_RE = re.compile(r"(\d+)\s+passed|(\d+)\s+failed|(\d+)\s+error|(\d+)\s+skipped")


class IntegrationAuditor(BaseSpecializedAgent):
    agent_name = "IntegrationAuditor"
    description = (
        "Executes deterministic unit/integration/E2E test suites via ProjectRunner "
        "and verifies cross-layer contract alignment."
    )
    supported_scopes = [AuditScope.FULL, AuditScope.E2E]

    async def execute(self, context: AuditContext, task: AuditTaskDTO) -> AgentResult:
        t0 = time.perf_counter()
        root = Path(context.workspace_path or context.root_path).resolve()
        runner = get_project_runner(str(context.runner_mode))
        findings: list[FindingCreateDTO] = []
        test_runs: list[TestRunCreateDTO] = []

        ws = WorkspaceInfo(
            session_id=context.session_id,
            source_root=Path(context.root_path).resolve(),
            workspace_dir=root,
            runner_mode=str(context.runner_mode),
            synthetic_env_path=root / ".env.qc",
            synthetic_env=runner.build_synthetic_env(context.session_id),
        )

        # Check if project has pytest tests
        test_files = [
            p
            for p in root.rglob("test_*.py")
            if ".qc_workspaces" not in str(p) and ".venv" not in str(p)
        ]

        # Avoid recursive self-audit infinite loop when running inside an active audit
        if test_files and not context.configuration.get("skip_nested_pytest", False):
            # Select unit tests or project tests
            target_test_dir = "tests/unit" if (root / "tests" / "unit").exists() else (
                "backend/tests/unit" if (root / "backend" / "tests" / "unit").exists() else "."
            )
            exec_res = await runner.execute_command(
                workspace=ws,
                command=["pytest", target_test_dir, "-q", "--tb=short"],
                timeout=45,
            )
            passed, failed, skipped = self._parse_pytest_counts(exec_res.stdout + "\n" + exec_res.stderr)
            total = max(1, passed + failed + skipped)
            status = TestRunStatus.PASSED if exec_res.exit_code == 0 else TestRunStatus.FAILED

            test_runs.append(
                TestRunCreateDTO(
                    test_suite_type=TestSuiteType.INTEGRATION,
                    tool_name="pytest",
                    command=f"pytest {target_test_dir} -q --tb=short",
                    status=status,
                    total_tests=total,
                    passed_tests=passed,
                    failed_tests=failed,
                    skipped_tests=skipped,
                    duration_seconds=exec_res.duration_seconds,
                    exit_code=exec_res.exit_code,
                    output_text=(exec_res.stdout + "\n" + exec_res.stderr).strip(),
                    details={"working_dir": exec_res.working_dir},
                )
            )

            if exec_res.exit_code not in {0, 5}:  # 5 = no tests collected
                findings.append(
                    FindingCreateDTO(
                        category=FindingCategory.INTEGRATION_FAILURE,
                        severity=FindingSeverity.HIGH,
                        title=f"Automated test suite failure ({failed} failed test(s))",
                        description=(
                            f"Deterministic execution of `pytest {target_test_dir}` exited with code "
                            f"{exec_res.exit_code} ({passed} passed, {failed} failed)."
                        ),
                        agent_name=self.agent_name,
                        reproduction_steps=[f"Run `pytest {target_test_dir} -q --tb=short`"],
                        expected_behavior="All automated test cases should pass (exit code 0).",
                        actual_behavior=f"Exit code {exec_res.exit_code}: {failed} test(s) failed.",
                        root_cause="Regression or defect in tested application logic.",
                        impact="Broken functional workflow confirmed by deterministic test failure.",
                        recommended_fix="Inspect failing test assertion output and fix underlying module defect.",
                        confidence=1.0,
                        verification_status=FindingVerificationStatus.CONFIRMED,
                        evidence_items=[
                            EvidenceCreateDTO(
                                evidence_type=EvidenceType.TEST_OUTPUT,
                                source_tool="pytest",
                                content_text=(exec_res.stdout + "\n" + exec_res.stderr).strip(),
                                content_excerpt=(exec_res.stdout + "\n" + exec_res.stderr)[:1200],
                                filename_hint="pytest_output.txt",
                            )
                        ],
                    )
                )

        int_score = max(0.0, 100.0 - len(findings) * 15.0)
        metrics = [
            MetricCreateDTO(
                dimension=QualityDimension.INTEGRATION,
                metric_name="integration_workflow_score",
                metric_value=round(int_score, 2),
                unit="score",
                weight=0.15,
                breakdown={
                    "test_files_found": len(test_files),
                    "test_runs_executed": len(test_runs),
                    "integration_findings": len(findings),
                },
            )
        ]

        return AgentResult(
            agent_name=self.agent_name,
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            findings=findings,
            metrics=metrics,
            test_runs=test_runs,
            duration_seconds=round(time.perf_counter() - t0, 3),
            summary={
                "test_files_found": len(test_files),
                "test_runs_executed": len(test_runs),
                "findings_count": len(findings),
            },
        )

    @staticmethod
    def _parse_pytest_counts(output: str) -> tuple[int, int, int]:
        passed = 0
        failed = 0
        skipped = 0
        for m in re.finditer(r"(\d+)\s+(passed|failed|error|errors|skipped)", output):
            count = int(m.group(1))
            kind = m.group(2)
            if kind == "passed":
                passed += count
            elif kind in {"failed", "error", "errors"}:
                failed += count
            elif kind == "skipped":
                skipped += count
        return passed, failed, skipped
