"""All 20 production SQLAlchemy 2.x PostgreSQL entities for the QC Intelligence Platform."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.infrastructure.database.session import Base

JSONB = JSON().with_variant(PG_JSONB(), "postgresql")
UUID = Uuid


def utc_now() -> datetime:
    return datetime.now(UTC)


# 1. User
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="ADMIN")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    owned_projects: Mapped[list["Project"]] = relationship("Project", back_populates="owner")
    memberships: Mapped[list["ProjectMember"]] = relationship("ProjectMember", back_populates="user")
    approvals: Mapped[list["Approval"]] = relationship("Approval", back_populates="reviewer")


# 2. Project
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    repository_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(128), nullable=False, default="main")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    detected_stack: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    owner: Mapped["User | None"] = relationship("User", back_populates="owned_projects")
    members: Mapped[list["ProjectMember"]] = relationship(
        "ProjectMember", back_populates="project", cascade="all, delete-orphan"
    )
    configuration: Mapped["ProjectConfiguration | None"] = relationship(
        "ProjectConfiguration", back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    audit_sessions: Mapped[list["AuditSession"]] = relationship(
        "AuditSession", back_populates="project", cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        "Finding", back_populates="project", cascade="all, delete-orphan"
    )


# 3. ProjectMember
class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="MAINTAINER")
    permissions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    project: Mapped["Project"] = relationship("Project", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="memberships")


# 4. ProjectConfiguration
class ProjectConfiguration(Base):
    __tablename__ = "project_configurations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="LOCAL")
    exclusions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    custom_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    service_startup_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    quality_gate_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    llm_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship("Project", back_populates="configuration")


# 5. AuditSession
class AuditSession(Base):
    __tablename__ = "audit_sessions"
    __table_args__ = (
        Index("ix_audit_sessions_project_status", "project_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="CREATED", index=True)
    current_phase: Mapped[str] = mapped_column(String(64), nullable=False, default="INITIALIZING")
    audit_scope: Mapped[str] = mapped_column(String(50), nullable=False, default="FULL")
    runner_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="LOCAL")
    commit_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manifest_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    scorecard: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    release_gate: Mapped[str] = mapped_column(
        String(50), nullable=False, default="INCOMPLETE_AUDIT"
    )
    environment_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    total_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    project: Mapped["Project"] = relationship("Project", back_populates="audit_sessions")
    tasks: Mapped[list["AuditTask"]] = relationship(
        "AuditTask", back_populates="session", cascade="all, delete-orphan"
    )
    repository_files: Mapped[list["RepositoryFile"]] = relationship(
        "RepositoryFile", back_populates="session", cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        "Finding", back_populates="session", cascade="all, delete-orphan"
    )
    evidence_items: Mapped[list["Evidence"]] = relationship(
        "Evidence", back_populates="session", cascade="all, delete-orphan"
    )
    test_runs: Mapped[list["TestRun"]] = relationship(
        "TestRun", back_populates="session", cascade="all, delete-orphan"
    )
    metrics: Mapped[list["AuditMetric"]] = relationship(
        "AuditMetric", back_populates="session", cascade="all, delete-orphan"
    )
    execution_logs: Mapped[list["ExecutionLog"]] = relationship(
        "ExecutionLog", back_populates="session", cascade="all, delete-orphan"
    )
    agent_executions: Mapped[list["AgentExecution"]] = relationship(
        "AgentExecution", back_populates="session", cascade="all, delete-orphan"
    )
    tool_executions: Mapped[list["ToolExecution"]] = relationship(
        "ToolExecution", back_populates="session", cascade="all, delete-orphan"
    )
    reports: Mapped[list["Report"]] = relationship(
        "Report", back_populates="session", cascade="all, delete-orphan"
    )
    events: Mapped[list["AuditEvent"]] = relationship(
        "AuditEvent", back_populates="session", cascade="all, delete-orphan"
    )


# 6. AuditTask
class AuditTask(Base):
    __tablename__ = "audit_tasks"
    __table_args__ = (
        Index("ix_audit_tasks_session_status", "session_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_key: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING", index=True)
    dependencies: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped["AuditSession"] = relationship("AuditSession", back_populates="tasks")
    agent_executions: Mapped[list["AgentExecution"]] = relationship(
        "AgentExecution", back_populates="task", cascade="all, delete-orphan"
    )


# 7. RepositoryFile
class RepositoryFile(Base):
    __tablename__ = "repository_files"
    __table_args__ = (
        Index("ix_repo_files_session_status", "session_id", "inspection_status"),
        UniqueConstraint("session_id", "relative_path", name="uq_session_file_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inspection_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PENDING", index=True
    )
    status_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_entrypoint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_test_file: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    component_boundary: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UNKNOWN", index=True
    )
    imports_dependencies: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["AuditSession"] = relationship("AuditSession", back_populates="repository_files")


# 8. Finding
class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("session_id", "fingerprint", name="uq_session_finding_fingerprint"),
        Index("ix_findings_project_severity", "project_id", "severity"),
        Index("ix_findings_session_status", "session_id", "lifecycle_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reproduction_steps: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    expected_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.85)
    verification_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="UNVERIFIED", index=True
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="NEW", index=True
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped["Project"] = relationship("Project", back_populates="findings")
    session: Mapped["AuditSession"] = relationship("AuditSession", back_populates="findings")
    evidence_records: Mapped[list["Evidence"]] = relationship(
        "Evidence", back_populates="finding", cascade="all, delete-orphan"
    )
    remediation_proposals: Mapped[list["RemediationProposal"]] = relationship(
        "RemediationProposal", back_populates="finding", cascade="all, delete-orphan"
    )


# 9. Evidence
class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_tasks.id", ondelete="SET NULL"), nullable=True
    )
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_tool: Mapped[str] = mapped_column(String(128), nullable=False)
    content_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped["AuditSession"] = relationship("AuditSession", back_populates="evidence_items")
    finding: Mapped["Finding | None"] = relationship("Finding", back_populates="evidence_records")


# 10. TestRun
class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_tasks.id", ondelete="SET NULL"), nullable=True
    )
    test_suite_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    total_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_evidence_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped["AuditSession"] = relationship("AuditSession", back_populates="test_runs")


# 11. AuditMetric
class AuditMetric(Base):
    __tablename__ = "audit_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dimension: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="score")
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped["AuditSession"] = relationship("AuditSession", back_populates="metrics")


# 12. ExecutionLog
class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_tasks.id", ondelete="SET NULL"), nullable=True
    )
    runner_type: Mapped[str] = mapped_column(String(32), nullable=False, default="LOCAL")
    command: Mapped[str] = mapped_column(Text, nullable=False)
    working_dir: Mapped[str] = mapped_column(String(1024), nullable=False)
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    timed_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stdout_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    stderr_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    stdout_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped["AuditSession"] = relationship("AuditSession", back_populates="execution_logs")


# 13. RemediationProposal
class RemediationProposal(Base):
    __tablename__ = "remediation_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="AWAITING_APPROVAL", index=True
    )
    root_cause_analysis: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    affected_files: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    expected_behavior: Mapped[str] = mapped_column(Text, nullable=False)
    potential_impact: Mapped[str] = mapped_column(Text, nullable=False)
    safety_check_results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    test_plan: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    rollback_procedure: Mapped[str] = mapped_column(Text, nullable=False)
    active_patch_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __mapper_args__ = {"version_id_col": version_id}

    finding: Mapped["Finding"] = relationship("Finding", back_populates="remediation_proposals")
    approvals: Mapped[list["Approval"]] = relationship(
        "Approval", back_populates="proposal", cascade="all, delete-orphan"
    )
    patches: Mapped[list["Patch"]] = relationship(
        "Patch", back_populates="proposal", cascade="all, delete-orphan"
    )


# 14. Approval
class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("remediation_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Human Reviewer")
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_patch_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    proposal: Mapped["RemediationProposal"] = relationship("RemediationProposal", back_populates="approvals")
    reviewer: Mapped["User | None"] = relationship("User", back_populates="approvals")


# 15. Patch
class Patch(Base):
    __tablename__ = "patches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("remediation_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sha256_checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_code: Mapped[str] = mapped_column(Text, nullable=False)
    unified_diff: Mapped[str] = mapped_column(Text, nullable=False)
    diff_artifact_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    working_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_commit_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    syntax_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    static_checks_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    proposal: Mapped["RemediationProposal"] = relationship("RemediationProposal", back_populates="patches")
    regression_runs: Mapped[list["RegressionRun"]] = relationship(
        "RegressionRun", back_populates="patch", cascade="all, delete-orphan"
    )


# 16. RegressionRun
class RegressionRun(Base):
    __tablename__ = "regression_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("test_runs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    issue_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    regressions_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pre_fix_comparison: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    post_fix_comparison: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    patch: Mapped["Patch"] = relationship("Patch", back_populates="regression_runs")


# 17. AgentExecution
class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RUNNING")
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    errors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["AuditSession"] = relationship("AuditSession", back_populates="agent_executions")
    task: Mapped["AuditTask"] = relationship("AuditTask", back_populates="agent_executions")


# 18. Report
class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_format: Mapped[str] = mapped_column(String(16), nullable=False, default="HTML")
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    release_recommendation: Mapped[str] = mapped_column(String(64), nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    audit_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    incomplete_checks: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped["AuditSession"] = relationship("AuditSession", back_populates="reports")


# 19. ToolExecution
class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_tasks.id", ondelete="SET NULL"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    is_mutating: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="COMPLETED")
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped["AuditSession"] = relationship("AuditSession", back_populates="tool_executions")


# 20. AuditEvent
class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="SYSTEM")
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped["AuditSession | None"] = relationship("AuditSession", back_populates="events")
