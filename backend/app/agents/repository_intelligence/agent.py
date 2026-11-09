"""Repository Intelligence Agent — Analyzes repository structure, stack, boundaries & dependencies."""

import json
import time

from backend.app.audit_engine.discovery.repository_intelligence_engine import (
    RepositoryIntelligenceEngine,
)
from backend.app.domain.enums.audit_enums import (
    AuditScope,
    EvidenceType,
    FindingCategory,
    FindingSeverity,
    FindingVerificationStatus,
    QualityDimension,
    TaskStatus,
)
from backend.app.domain.interfaces.contracts import (
    AgentResult,
    AuditContext,
    AuditTaskDTO,
    BaseSpecializedAgent,
    EvidenceCreateDTO,
    FindingCreateDTO,
    MetricCreateDTO,
)


class RepositoryIntelligenceAgent(BaseSpecializedAgent):
    agent_name = "RepositoryIntelligenceAgent"
    description = "Discovers repository file inventory, languages, frameworks, boundaries, and dependencies."
    supported_scopes = [
        AuditScope.FULL,
        AuditScope.CODE,
        AuditScope.BACKEND,
        AuditScope.FRONTEND,
        AuditScope.DATABASE,
        AuditScope.SECURITY,
        AuditScope.PERFORMANCE,
        AuditScope.E2E,
    ]

    async def execute(self, context: AuditContext, task: AuditTaskDTO) -> AgentResult:
        t0 = time.perf_counter()
        exclusions = context.configuration.get("exclusions", [])
        engine = RepositoryIntelligenceEngine(custom_exclusions=exclusions)
        discovery = engine.discover_repository(context.root_path)
        manifest = discovery["manifest"]
        coverage = manifest["coverage"]

        findings: list[FindingCreateDTO] = []
        evidence_manifest = EvidenceCreateDTO(
            evidence_type=EvidenceType.SCANNER_REPORT,
            source_tool="RepositoryIntelligenceEngine",
            content_text=json.dumps(manifest, indent=2, default=str),
            content_excerpt=f"Discovered {coverage['files_discovered']} files ({coverage['files_in_scope']} in scope, {coverage['inspection_coverage_percent']}% inspected).",
            metadata_json=coverage,
            filename_hint="project_manifest.json",
        )

        if coverage["files_failed"] > 0:
            findings.append(
                FindingCreateDTO(
                    category=FindingCategory.INCOMPLETE_IMPLEMENTATION,
                    severity=FindingSeverity.MEDIUM,
                    title="Unreadable or corrupt files encountered during repository discovery",
                    description=f"{coverage['files_failed']} file(s) failed inspection during repository discovery.",
                    agent_name=self.agent_name,
                    reproduction_steps=["Run qc-agent discover against the repository root."],
                    expected_behavior="All in-scope source files should be readable and UTF-8 decodable.",
                    actual_behavior=f"{coverage['files_failed']} file(s) failed to read.",
                    root_cause="Corrupted file encoding or restricted file permissions.",
                    impact="Incomplete static and security analysis on unreadable files.",
                    recommended_fix="Convert non-UTF-8 source files to UTF-8 or add binary extensions to exclusions.",
                    confidence=0.95,
                    verification_status=FindingVerificationStatus.CONFIRMED,
                    evidence_items=[evidence_manifest],
                )
            )

        metrics = [
            MetricCreateDTO(
                dimension=QualityDimension.ARCHITECTURE,
                metric_name="inspection_coverage_percent",
                metric_value=float(coverage["inspection_coverage_percent"]),
                unit="percent",
                weight=0.10,
                breakdown=coverage,
            )
        ]

        duration = round(time.perf_counter() - t0, 3)
        return AgentResult(
            agent_name=self.agent_name,
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            findings=findings,
            metrics=metrics,
            duration_seconds=duration,
            summary={
                "manifest": manifest,
                "files_count": len(discovery["files"]),
            },
        )
