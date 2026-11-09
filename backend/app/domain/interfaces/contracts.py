"""Core interfaces and Pydantic contracts for Agents, Tools, Runners, and LLM Providers."""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.domain.enums.audit_enums import (
    AuditScope,
    EvidenceType,
    FindingCategory,
    FindingSeverity,
    FindingVerificationStatus,
    QualityDimension,
    RunnerMode,
    TaskStatus,
    TestRunStatus,
    TestSuiteType,
)


class AuditContext(BaseModel):
    session_id: UUID
    project_id: UUID
    project_name: str
    root_path: str
    workspace_path: str
    runner_mode: RunnerMode = RunnerMode.LOCAL
    audit_scope: AuditScope = AuditScope.FULL
    manifest: dict[str, Any] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)


class AuditTaskDTO(BaseModel):
    id: UUID
    task_key: str
    agent_type: str
    phase: str
    status: TaskStatus
    dependencies: list[str] = Field(default_factory=list)
    input_payload: dict[str, Any] = Field(default_factory=dict)


class EvidenceCreateDTO(BaseModel):
    evidence_type: EvidenceType
    source_tool: str
    content_bytes: bytes | None = None
    content_text: str | None = None
    content_excerpt: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    filename_hint: str = "evidence.txt"


class FindingCreateDTO(BaseModel):
    category: FindingCategory | str
    severity: FindingSeverity
    title: str
    description: str
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    agent_name: str
    reproduction_steps: list[str] = Field(default_factory=list)
    expected_behavior: str | None = None
    actual_behavior: str | None = None
    root_cause: str | None = None
    impact: str | None = None
    recommended_fix: str | None = None
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    verification_status: FindingVerificationStatus = FindingVerificationStatus.UNVERIFIED
    evidence_items: list[EvidenceCreateDTO] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)


class MetricCreateDTO(BaseModel):
    dimension: QualityDimension
    metric_name: str
    metric_value: float
    unit: str = "score"
    weight: float = 0.1
    breakdown: dict[str, Any] = Field(default_factory=dict)


class TestRunCreateDTO(BaseModel):
    test_suite_type: TestSuiteType
    tool_name: str
    command: str
    status: TestRunStatus
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    duration_seconds: float = 0.0
    exit_code: int = 0
    output_text: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    agent_name: str
    task_id: UUID
    status: TaskStatus
    findings: list[FindingCreateDTO] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    metrics: list[MetricCreateDTO] = Field(default_factory=list)
    test_runs: list[TestRunCreateDTO] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_provider: str | None = None
    llm_model: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class BaseSpecializedAgent(ABC):
    """Required interface for all 10 specialized QC audit agents."""

    agent_name: str
    description: str
    supported_scopes: list[AuditScope]

    @abstractmethod
    async def execute(
        self,
        context: AuditContext,
        task: AuditTaskDTO,
    ) -> AgentResult:
        """Execute assigned task deterministically and return validated AgentResult."""
