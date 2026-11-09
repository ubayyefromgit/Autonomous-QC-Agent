"""Quality Scoring and Independent Release Gate Evaluation Engine."""

from typing import Any

from backend.app.domain.enums.audit_enums import (
    FindingLifecycleStatus,
    FindingSeverity,
    FindingVerificationStatus,
    QualityDimension,
    ReleaseGateStatus,
)
from shared.constants.defaults import QUALITY_DIMENSION_WEIGHTS

CATEGORY_TO_DIMENSION: dict[str, QualityDimension] = {
    "SYNTAX_ERROR": QualityDimension.CODE_QUALITY,
    "LOGIC_DEFECT": QualityDimension.CODE_QUALITY,
    "DEAD_CODE": QualityDimension.CODE_QUALITY,
    "DUPLICATE_CODE": QualityDimension.CODE_QUALITY,
    "EXCEPTION_HANDLING": QualityDimension.CODE_QUALITY,
    "TYPE_ERROR": QualityDimension.CODE_QUALITY,
    "COMPLEXITY": QualityDimension.CODE_QUALITY,
    "INCOMPLETE_IMPLEMENTATION": QualityDimension.CODE_QUALITY,
    "ARCHITECTURE_VIOLATION": QualityDimension.ARCHITECTURE,
    "CIRCULAR_DEPENDENCY": QualityDimension.ARCHITECTURE,
    "API_CONTRACT_FAILURE": QualityDimension.BACKEND_RELIABILITY,
    "BACKEND_RUNTIME_ERROR": QualityDimension.BACKEND_RELIABILITY,
    "FRONTEND_UI_DEFECT": QualityDimension.FRONTEND_QUALITY,
    "BROWSER_CONSOLE_ERROR": QualityDimension.FRONTEND_QUALITY,
    "NETWORK_FAILURE": QualityDimension.FRONTEND_QUALITY,
    "DATABASE_INTEGRITY": QualityDimension.INTEGRATION,
    "MIGRATION_DEFECT": QualityDimension.INTEGRATION,
    "INTEGRATION_FAILURE": QualityDimension.INTEGRATION,
    "SECURITY_VULNERABILITY": QualityDimension.SECURITY,
    "SECRET_EXPOSURE": QualityDimension.SECURITY,
    "DEPENDENCY_VULNERABILITY": QualityDimension.SECURITY,
    "PERFORMANCE_BOTTLENECK": QualityDimension.PERFORMANCE,
}

SEVERITY_PENALTY: dict[str, float] = {
    FindingSeverity.CRITICAL.value: 25.0,
    FindingSeverity.HIGH.value: 12.0,
    FindingSeverity.MEDIUM.value: 5.0,
    FindingSeverity.LOW.value: 2.0,
    FindingSeverity.INFORMATIONAL.value: 0.5,
}


class QualityScoringEngine:
    """Computes transparent 8-dimension quality scorecards and independent release gate decisions."""

    def evaluate(
        self,
        findings: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        test_runs: list[dict[str, Any]],
        coverage_percent: float,
        custom_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = custom_policy or {}
        dimension_penalties: dict[str, float] = {dim.value: 0.0 for dim in QualityDimension}
        dimension_finding_counts: dict[str, int] = {dim.value: 0 for dim in QualityDimension}

        unresolved_critical_count = 0
        unresolved_high_count = 0
        confirmed_critical_security = 0

        for f in findings:
            lifecycle = f.get("lifecycle_status", FindingLifecycleStatus.NEW.value)
            verification = f.get("verification_status", FindingVerificationStatus.UNVERIFIED.value)
            if lifecycle in {
                FindingLifecycleStatus.RESOLVED.value,
                FindingLifecycleStatus.ACCEPTED_RISK.value,
            } or verification == FindingVerificationStatus.REJECTED.value:
                continue

            severity = f.get("severity", FindingSeverity.MEDIUM.value)
            category = f.get("category", "LOGIC_DEFECT")
            dim = CATEGORY_TO_DIMENSION.get(category, QualityDimension.CODE_QUALITY).value

            penalty = SEVERITY_PENALTY.get(severity, 5.0)
            dimension_penalties[dim] += penalty
            dimension_finding_counts[dim] += 1

            if severity == FindingSeverity.CRITICAL.value:
                unresolved_critical_count += 1
                if dim == QualityDimension.SECURITY.value and verification in {
                    FindingVerificationStatus.CONFIRMED.value,
                    FindingVerificationStatus.REPRODUCED.value,
                }:
                    confirmed_critical_security += 1
            elif severity == FindingSeverity.HIGH.value:
                unresolved_high_count += 1

        # Evaluate Test Quality based on actual test runs
        total_tests = sum(tr.get("total_tests", 0) for tr in test_runs)
        passed_tests = sum(tr.get("passed_tests", 0) for tr in test_runs)
        failed_tests = sum(tr.get("failed_tests", 0) for tr in test_runs)

        if total_tests == 0:
            test_quality_score = 65.0
        else:
            pass_rate = passed_tests / max(1, total_tests)
            test_quality_score = round(max(0.0, min(100.0, pass_rate * 100.0 - (failed_tests * 4.0))), 2)

        dimensions_result: dict[str, dict[str, Any]] = {}
        weighted_total = 0.0

        for dim in QualityDimension:
            weight = QUALITY_DIMENSION_WEIGHTS.get(dim.value, 0.1)
            if dim == QualityDimension.TEST_QUALITY:
                raw_score = test_quality_score
            else:
                raw_score = max(0.0, round(100.0 - dimension_penalties[dim.value], 2))

            weighted_contribution = round(raw_score * weight, 2)
            weighted_total += weighted_contribution
            dimensions_result[dim.value] = {
                "score": raw_score,
                "weight": weight,
                "weighted_score": weighted_contribution,
                "active_findings": dimension_finding_counts[dim.value],
            }

        overall_score = round(weighted_total, 2)

        # Check task completion for essential audit checks
        incomplete_tasks = [
            t.get("task_key", "unknown")
            for t in tasks
            if t.get("status") not in {"COMPLETED"}
        ]
        failed_tasks = [
            t.get("task_key", "unknown")
            for t in tasks
            if t.get("status") in {"FAILED", "CANCELLED"}
        ]

        blocking_reasons: list[str] = []
        warning_reasons: list[str] = []

        if len(tasks) == 0 or len(incomplete_tasks) > 0:
            blocking_reasons.append(
                f"Incomplete audit tasks: {', '.join(incomplete_tasks) if incomplete_tasks else 'no tasks executed'}"
            )
        if coverage_percent < float(policy.get("min_inspection_coverage_percent", 80.0)):
            blocking_reasons.append(
                f"Repository inspection coverage ({coverage_percent}%) is below required threshold."
            )
        if unresolved_critical_count > int(policy.get("max_critical_findings", 0)):
            blocking_reasons.append(
                f"{unresolved_critical_count} unresolved CRITICAL finding(s) detected."
            )
        if confirmed_critical_security > 0:
            blocking_reasons.append(
                f"{confirmed_critical_security} confirmed CRITICAL security vulnerability(ies) present."
            )

        if unresolved_high_count > int(policy.get("max_high_findings_for_clean_approval", 0)):
            warning_reasons.append(
                f"{unresolved_high_count} unresolved HIGH severity finding(s) require engineering review."
            )
        if failed_tests > 0:
            warning_reasons.append(f"{failed_tests} deterministic test case(s) failed during execution.")

        # Determine Release Gate state (Strictly separate from score)
        if len(tasks) == 0 or len(incomplete_tasks) > 0:
            release_gate = ReleaseGateStatus.INCOMPLETE_AUDIT.value
        elif unresolved_critical_count > int(policy.get("max_critical_findings", 0)) or overall_score < float(
            policy.get("min_approval_score", 60.0)
        ):
            release_gate = ReleaseGateStatus.REJECTED.value
        elif warning_reasons or overall_score < 90.0:
            release_gate = ReleaseGateStatus.APPROVED_WITH_WARNINGS.value
        else:
            release_gate = ReleaseGateStatus.APPROVED.value

        return {
            "overall_score": overall_score,
            "release_gate": release_gate,
            "audit_complete": len(tasks) > 0 and len(incomplete_tasks) == 0,
            "dimensions": dimensions_result,
            "blocking_reasons": blocking_reasons,
            "warning_reasons": warning_reasons,
            "incomplete_tasks": incomplete_tasks,
            "failed_tasks": failed_tasks,
            "summary_counts": {
                "unresolved_critical": unresolved_critical_count,
                "unresolved_high": unresolved_high_count,
                "total_tests_executed": total_tests,
                "passed_tests": passed_tests,
                "failed_tests": failed_tests,
                "inspection_coverage_percent": coverage_percent,
            },
        }
