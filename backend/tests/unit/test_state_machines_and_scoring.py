"""Unit tests for deterministic State Machines, Quality Scoring, Release Gates, and ToolRegistry."""

from uuid import uuid4

import pytest
from pydantic import BaseModel

from backend.app.agents.registry.tool_registry import ToolDefinition, ToolRegistry
from backend.app.audit_engine.scoring.scoring_engine import QualityScoringEngine
from backend.app.core.exceptions import AuthorizationError, SecurityPolicyViolationError
from backend.app.core.security import (
    compute_finding_fingerprint,
    compute_patch_checksum,
)
from backend.app.domain.entities.state_machines import (
    AuditStateMachine,
    FindingStateMachine,
    InvalidStateTransitionError,
    RemediationApprovalStateMachine,
)
from backend.app.domain.enums.audit_enums import (
    AuditSessionStatus,
    FindingLifecycleStatus,
    FindingVerificationStatus,
    ProposalStatus,
    ReleaseGateStatus,
)


def test_audit_state_machine_transitions() -> None:
    AuditStateMachine.validate_transition(
        AuditSessionStatus.CREATED, AuditSessionStatus.DISCOVERING
    )
    AuditStateMachine.validate_transition(
        AuditSessionStatus.DISCOVERING, AuditSessionStatus.PLANNING
    )
    AuditStateMachine.validate_transition(
        AuditSessionStatus.EXECUTING, AuditSessionStatus.INTERRUPTED
    )
    AuditStateMachine.validate_transition(
        AuditSessionStatus.INTERRUPTED, AuditSessionStatus.EXECUTING
    )
    with pytest.raises(InvalidStateTransitionError):
        AuditStateMachine.validate_transition(
            AuditSessionStatus.COMPLETED, AuditSessionStatus.EXECUTING
        )


def test_finding_evidence_first_and_resolution_rules() -> None:
    # Cannot promote to CONFIRMED with 0 evidence items
    with pytest.raises(InvalidStateTransitionError):
        FindingStateMachine.validate_verification_promotion(
            FindingVerificationStatus.CONFIRMED, evidence_count=0
        )

    # Allowed when evidence is attached
    FindingStateMachine.validate_verification_promotion(
        FindingVerificationStatus.CONFIRMED, evidence_count=1
    )

    # Cannot mark RESOLVED if regression verification has not passed
    with pytest.raises(InvalidStateTransitionError):
        FindingStateMachine.validate_resolution(
            FindingLifecycleStatus.RESOLVED, regression_passed=False
        )
    FindingStateMachine.validate_resolution(
        FindingLifecycleStatus.RESOLVED, regression_passed=True
    )


def test_remediation_checksum_binding_enforcement() -> None:
    checksum = compute_patch_checksum("app/main.py", "--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-x=1\n+x=2")

    # Cannot apply if status is AWAITING_APPROVAL
    with pytest.raises(InvalidStateTransitionError):
        RemediationApprovalStateMachine.verify_checksum_for_application(
            proposal_status=ProposalStatus.AWAITING_APPROVAL,
            active_patch_checksum=checksum,
            approved_patch_checksum=checksum,
        )

    # Cannot apply if checksum changed after approval
    with pytest.raises(InvalidStateTransitionError):
        RemediationApprovalStateMachine.verify_checksum_for_application(
            proposal_status=ProposalStatus.APPROVED,
            active_patch_checksum=checksum,
            approved_patch_checksum="tampered-checksum-value",
        )

    # Succeeds when APPROVED and checksums match
    RemediationApprovalStateMachine.verify_checksum_for_application(
        proposal_status=ProposalStatus.APPROVED,
        active_patch_checksum=checksum,
        approved_patch_checksum=checksum,
    )


def test_quality_scoring_and_release_gate_independence() -> None:
    engine = QualityScoringEngine()

    # Case 1: Incomplete audit must always return INCOMPLETE_AUDIT even with 0 findings
    res_incomplete = engine.evaluate(
        findings=[],
        tasks=[{"task_key": "code_quality_audit", "status": "PENDING"}],
        test_runs=[],
        coverage_percent=100.0,
    )
    assert res_incomplete["release_gate"] == ReleaseGateStatus.INCOMPLETE_AUDIT.value
    assert res_incomplete["audit_complete"] is False

    # Case 2: Critical confirmed finding must block approval (REJECTED) even if score is high
    res_critical = engine.evaluate(
        findings=[
            {
                "severity": "CRITICAL",
                "category": "SECURITY_VULNERABILITY",
                "verification_status": "CONFIRMED",
                "lifecycle_status": "NEW",
            }
        ],
        tasks=[{"task_key": "security_audit", "status": "COMPLETED"}],
        test_runs=[{"total_tests": 20, "passed_tests": 20, "failed_tests": 0}],
        coverage_percent=100.0,
    )
    assert res_critical["overall_score"] >= 90.0
    assert res_critical["release_gate"] == ReleaseGateStatus.REJECTED.value

    # Case 3: Clean completed audit with passing tests gets APPROVED
    res_clean = engine.evaluate(
        findings=[],
        tasks=[{"task_key": "code_quality_audit", "status": "COMPLETED"}],
        test_runs=[{"total_tests": 25, "passed_tests": 25, "failed_tests": 0}],
        coverage_percent=98.5,
    )
    assert res_clean["release_gate"] == ReleaseGateStatus.APPROVED.value
    assert res_clean["overall_score"] == 100.0


@pytest.mark.asyncio
async def test_tool_registry_permissions_and_mutation_gate() -> None:
    class SampleInput(BaseModel):
        target: str

    class SampleOutput(BaseModel):
        ok: bool

    async def sample_handler(inp: SampleInput) -> SampleOutput:
        return SampleOutput(ok=bool(inp.target))

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="apply_git_patch",
            description="Applies patch to branch",
            input_schema=SampleInput,
            output_schema=SampleOutput,
            required_permissions=["git:write"],
            is_mutating=True,
        ),
        sample_handler,
    )

    # Denied when permission is missing
    with pytest.raises(AuthorizationError):
        await registry.execute_tool(
            "apply_git_patch",
            {"target": "main.py"},
            agent_permissions={"git:read"},
            has_human_approval=True,
        )

    # Denied when mutating tool is called without human approval
    with pytest.raises(SecurityPolicyViolationError):
        await registry.execute_tool(
            "apply_git_patch",
            {"target": "main.py"},
            agent_permissions={"git:write"},
            has_human_approval=False,
        )

    # Allowed when permission and human approval are both satisfied
    out = await registry.execute_tool(
        "apply_git_patch",
        {"target": "main.py"},
        agent_permissions={"git:write"},
        has_human_approval=True,
    )
    assert out["ok"] is True


def test_finding_fingerprint_stability() -> None:
    proj_id = str(uuid4())
    fp1 = compute_finding_fingerprint(proj_id, "LOGIC_DEFECT", "app\\service.py", "Mutable Default", 12)
    fp2 = compute_finding_fingerprint(proj_id, "LOGIC_DEFECT", "app/service.py", "mutable default ", 14)
    assert fp1 == fp2
