"""Pydantic V2 request and response schemas for the REST API v1."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --- Auth & Users ---
class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str = Field(min_length=2)
    role: str = "ADMIN"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# --- Projects & Configuration ---
class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    root_path: str = Field(min_length=1)
    repository_url: str | None = None
    default_branch: str = "main"
    execution_mode: str = "LOCAL"
    exclusions: list[str] = Field(default_factory=list)


class ProjectConfigUpdateRequest(BaseModel):
    execution_mode: str | None = None
    exclusions: list[str] | None = None
    custom_rules: dict[str, Any] | None = None
    service_startup_config: dict[str, Any] | None = None
    quality_gate_policy: dict[str, Any] | None = None
    llm_config: dict[str, Any] | None = None
    retention_days: int | None = None


class ProjectConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    execution_mode: str
    exclusions: list[str]
    custom_rules: dict[str, Any]
    service_startup_config: dict[str, Any]
    quality_gate_policy: dict[str, Any]
    llm_config: dict[str, Any]
    retention_days: int
    updated_at: datetime


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    description: str | None
    root_path: str
    repository_url: str | None
    default_branch: str
    owner_id: UUID | None
    detected_stack: dict[str, Any]
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    configuration: ProjectConfigurationResponse | None = None
    total_audits: int = 0
    last_audit_status: str | None = None
    last_audit_score: float | None = None
    last_release_gate: str | None = None
    unresolved_findings_count: int = 0


# --- Repository Files & Manifest ---
class RepositoryFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    project_id: UUID
    relative_path: str
    file_type: str
    language: str
    size_bytes: int
    line_count: int
    sha256_hash: str | None
    inspection_status: str
    status_reason: str | None
    is_entrypoint: bool
    is_test_file: bool
    component_boundary: str
    imports_dependencies: list[str]
    inspected_at: datetime | None


# --- Audit Sessions & Tasks ---
class AuditCreateRequest(BaseModel):
    audit_scope: str = "FULL"
    runner_mode: str = "LOCAL"
    custom_instructions: str = ""
    project_documentation: str = ""
    run_immediately: bool = True
    run_synchronously: bool = False


class AuditTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    task_key: str
    agent_type: str
    phase: str
    status: str
    dependencies: list[str]
    result_summary: dict[str, Any]
    attempts: int
    duration_seconds: float | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None


class AuditMetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    dimension: str
    metric_name: str
    metric_value: float
    unit: str
    weight: float
    breakdown: dict[str, Any]
    recorded_at: datetime


class TestRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    task_id: UUID | None
    test_suite_type: str
    tool_name: str
    command: str
    status: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    skipped_tests: int
    duration_seconds: float
    exit_code: int
    output_evidence_uri: str | None
    details: dict[str, Any]
    executed_at: datetime


class ExecutionLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    task_id: UUID | None
    runner_type: str
    command: str
    working_dir: str
    exit_code: int
    duration_seconds: float
    timed_out: bool
    stdout_preview: str | None
    stderr_preview: str | None
    executed_at: datetime


class AuditSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    project_name: str | None = None
    triggered_by: UUID | None
    status: str
    current_phase: str
    audit_scope: str
    runner_mode: str
    commit_hash: str | None
    branch_name: str | None
    manifest_summary: dict[str, Any]
    scorecard: dict[str, Any]
    overall_score: float | None
    release_gate: str
    environment_snapshot: dict[str, Any]
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    error_summary: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class AuditProgressResponse(BaseModel):
    audit_id: UUID
    project_id: UUID
    status: str
    current_phase: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    progress_percent: float
    active_agents: list[str]
    elapsed_seconds: float
    tasks: list[AuditTaskResponse]
    recent_logs: list[ExecutionLogResponse]


# --- Findings & Evidence ---
class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    task_id: UUID | None
    finding_id: UUID | None
    evidence_type: str
    storage_uri: str
    sha256_checksum: str
    source_tool: str
    content_excerpt: str | None
    metadata_json: dict[str, Any]
    created_at: datetime


class FindingUpdateRequest(BaseModel):
    verification_status: str | None = None
    lifecycle_status: str | None = None
    recommended_fix: str | None = None
    root_cause: str | None = None


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    session_id: UUID
    fingerprint: str
    category: str
    severity: str
    title: str
    description: str
    file_path: str | None
    line_start: int | None
    line_end: int | None
    agent_name: str
    reproduction_steps: list[str]
    expected_behavior: str | None
    actual_behavior: str | None
    root_cause: str | None
    impact: str | None
    recommended_fix: str | None
    confidence: float
    verification_status: str
    lifecycle_status: str
    occurrence_count: int
    first_seen_session_id: UUID | None
    created_at: datetime
    updated_at: datetime
    evidence_count: int = 0


# --- Remediation, Approvals, Patches & Regressions ---
class ProposalCreateRequest(BaseModel):
    custom_instructions: str | None = None
    proposed_code_override: str | None = None


class ApprovalDecisionRequest(BaseModel):
    patch_checksum: str
    reviewer_name: str = "Principal Engineer"
    comments: str | None = None


class PatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    proposal_id: UUID
    sha256_checksum: str
    target_file_path: str
    original_code: str
    proposed_code: str
    unified_diff: str
    working_branch: str | None
    base_commit_hash: str | None
    syntax_valid: bool
    static_checks_passed: bool
    applied_at: datetime | None
    created_at: datetime


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    proposal_id: UUID
    reviewer_id: UUID | None
    reviewer_name: str
    decision: str
    approved_patch_checksum: str
    comments: str | None
    is_valid: bool
    decided_at: datetime


class RegressionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    patch_id: UUID
    test_run_id: UUID | None
    status: str
    issue_resolved: bool
    regressions_detected: bool
    pre_fix_comparison: dict[str, Any]
    post_fix_comparison: dict[str, Any]
    verified_at: datetime


class RemediationProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    finding_id: UUID
    session_id: UUID
    status: str
    root_cause_analysis: str
    explanation: str
    affected_files: list[str]
    expected_behavior: str
    potential_impact: str
    safety_check_results: dict[str, Any]
    test_plan: list[str]
    rollback_procedure: str
    active_patch_checksum: str
    version_id: int
    created_at: datetime
    updated_at: datetime
    patches: list[PatchResponse] = Field(default_factory=list)
    approvals: list[ApprovalResponse] = Field(default_factory=list)
    regression_runs: list[RegressionRunResponse] = Field(default_factory=list)


# --- Reports ---
class ReportGenerateRequest(BaseModel):
    report_format: str = "HTML"


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    report_format: str
    storage_uri: str
    sha256_checksum: str
    release_recommendation: str
    overall_score: float
    audit_complete: bool
    incomplete_checks: list[str]
    generated_at: datetime
