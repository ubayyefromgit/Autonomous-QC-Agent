"""Deterministic state machines for Audit Sessions, Findings, and Remediation Approvals."""

from backend.app.domain.enums.audit_enums import (
    AuditSessionStatus,
    FindingLifecycleStatus,
    FindingVerificationStatus,
    ProposalStatus,
)


class InvalidStateTransitionError(ValueError):
    """Raised when an invalid state transition is attempted."""


AUDIT_SESSION_TRANSITIONS: dict[AuditSessionStatus, set[AuditSessionStatus]] = {
    AuditSessionStatus.CREATED: {
        AuditSessionStatus.DISCOVERING,
        AuditSessionStatus.CANCELLED,
        AuditSessionStatus.FAILED,
    },
    AuditSessionStatus.DISCOVERING: {
        AuditSessionStatus.PLANNING,
        AuditSessionStatus.FAILED,
        AuditSessionStatus.CANCELLED,
        AuditSessionStatus.INTERRUPTED,
    },
    AuditSessionStatus.PLANNING: {
        AuditSessionStatus.EXECUTING,
        AuditSessionStatus.FAILED,
        AuditSessionStatus.CANCELLED,
        AuditSessionStatus.INTERRUPTED,
    },
    AuditSessionStatus.EXECUTING: {
        AuditSessionStatus.VALIDATING,
        AuditSessionStatus.FAILED,
        AuditSessionStatus.CANCELLED,
        AuditSessionStatus.INTERRUPTED,
    },
    AuditSessionStatus.VALIDATING: {
        AuditSessionStatus.SCORING,
        AuditSessionStatus.FAILED,
        AuditSessionStatus.CANCELLED,
    },
    AuditSessionStatus.SCORING: {
        AuditSessionStatus.REPORTING,
        AuditSessionStatus.COMPLETED,
        AuditSessionStatus.FAILED,
    },
    AuditSessionStatus.REPORTING: {
        AuditSessionStatus.COMPLETED,
        AuditSessionStatus.FAILED,
    },
    AuditSessionStatus.INTERRUPTED: {
        AuditSessionStatus.DISCOVERING,
        AuditSessionStatus.PLANNING,
        AuditSessionStatus.EXECUTING,
        AuditSessionStatus.CANCELLED,
        AuditSessionStatus.FAILED,
    },
    AuditSessionStatus.COMPLETED: set(),
    AuditSessionStatus.FAILED: {AuditSessionStatus.DISCOVERING, AuditSessionStatus.EXECUTING},
    AuditSessionStatus.CANCELLED: set(),
}


PROPOSAL_STATE_TRANSITIONS: dict[ProposalStatus, set[ProposalStatus]] = {
    ProposalStatus.DRAFT: {ProposalStatus.SAFETY_CHECKED, ProposalStatus.INVALIDATED},
    ProposalStatus.SAFETY_CHECKED: {
        ProposalStatus.AWAITING_APPROVAL,
        ProposalStatus.APPROVED,
        ProposalStatus.REJECTED,
        ProposalStatus.INVALIDATED,
    },
    ProposalStatus.AWAITING_APPROVAL: {
        ProposalStatus.APPROVED,
        ProposalStatus.REJECTED,
        ProposalStatus.INVALIDATED,
    },
    ProposalStatus.APPROVED: {
        ProposalStatus.APPLIED,
        ProposalStatus.INVALIDATED,
        ProposalStatus.REJECTED,
    },
    ProposalStatus.REJECTED: {ProposalStatus.DRAFT, ProposalStatus.SAFETY_CHECKED},
    ProposalStatus.INVALIDATED: {ProposalStatus.SAFETY_CHECKED, ProposalStatus.DRAFT},
    ProposalStatus.APPLIED: {ProposalStatus.VERIFIED, ProposalStatus.FAILED},
    ProposalStatus.VERIFIED: set(),
    ProposalStatus.FAILED: {ProposalStatus.DRAFT, ProposalStatus.SAFETY_CHECKED},
}


class AuditStateMachine:
    """Validates and executes AuditSession state transitions."""

    @staticmethod
    def validate_transition(
        current: AuditSessionStatus, target: AuditSessionStatus
    ) -> None:
        if current == target:
            return
        allowed = AUDIT_SESSION_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition AuditSession from {current} to {target}. Allowed: {sorted(allowed)}"
            )


class FindingStateMachine:
    """Enforces Evidence-First verification and lifecycle transitions for Findings."""

    @staticmethod
    def validate_verification_promotion(
        target: FindingVerificationStatus, evidence_count: int
    ) -> None:
        if target in {
            FindingVerificationStatus.CONFIRMED,
            FindingVerificationStatus.REPRODUCED,
        } and evidence_count < 1:
            raise InvalidStateTransitionError(
                f"Cannot promote finding to {target} without supporting evidence (evidence_count={evidence_count})."
            )

    @staticmethod
    def validate_resolution(
        target: FindingLifecycleStatus, regression_passed: bool
    ) -> None:
        if target == FindingLifecycleStatus.RESOLVED and not regression_passed:
            raise InvalidStateTransitionError(
                "Cannot mark finding as RESOLVED until regression verification has passed."
            )


class RemediationApprovalStateMachine:
    """Enforces strict checksum-bound human approval and regression verification for patches."""

    @staticmethod
    def validate_transition(current: ProposalStatus, target: ProposalStatus) -> None:
        if current == target:
            return
        allowed = PROPOSAL_STATE_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition RemediationProposal from {current} to {target}."
            )

    @staticmethod
    def verify_checksum_for_application(
        proposal_status: ProposalStatus,
        active_patch_checksum: str,
        approved_patch_checksum: str | None,
    ) -> None:
        if proposal_status != ProposalStatus.APPROVED:
            raise InvalidStateTransitionError(
                f"Patch cannot be applied unless proposal status is APPROVED (current={proposal_status})."
            )
        if not approved_patch_checksum or active_patch_checksum != approved_patch_checksum:
            raise InvalidStateTransitionError(
                "Patch checksum mismatch: approval is invalidated because the patch changed after approval."
            )

