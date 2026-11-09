"""RemediationService — Manages root-cause proposals, SHA-256 checksum approvals, isolated branch application & regressions."""

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.code_auditor.agent import CodeQualityAgent
from backend.app.agents.remediation.agent import RemediationAgent
from backend.app.agents.security_auditor.agent import SecurityAuditor
from backend.app.audit_engine.evidence.evidence_service import EvidenceService
from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApprovalIntegrityError, EntityNotFoundError
from backend.app.core.security import compute_patch_checksum
from backend.app.domain.entities.state_machines import RemediationApprovalStateMachine
from backend.app.domain.enums.audit_enums import (
    ApprovalDecision,
    AuditScope,
    EvidenceType,
    FindingLifecycleStatus,
    ProposalStatus,
    RunnerMode,
    TaskStatus,
    TestRunStatus,
    TestSuiteType,
)
from backend.app.domain.interfaces.contracts import AuditContext, AuditTaskDTO
from backend.app.models.entities import (
    Approval,
    AuditEvent,
    Finding,
    Patch,
    Project,
    RegressionRun,
    RemediationProposal,
    TestRun,
)


class RemediationService:
    """Enforces human-controlled remediation, SHA-256 checksum binding, isolated branches, and regression verification."""

    def __init__(self) -> None:
        self.remediation_agent = RemediationAgent()
        self.evidence_service = EvidenceService()

    async def create_proposal(
        self,
        db: AsyncSession,
        finding_id: UUID,
        proposed_code_override: str | None = None,
    ) -> RemediationProposal:
        finding = await db.get(Finding, finding_id)
        if finding is None:
            raise EntityNotFoundError("Finding", finding_id)

        project = await db.get(Project, finding.project_id)
        if project is None:
            raise EntityNotFoundError("Project", finding.project_id)

        payload = await self.remediation_agent.generate_proposal_payload(
            project_root=project.root_path,
            finding_data={
                "id": str(finding.id),
                "title": finding.title,
                "category": finding.category,
                "severity": finding.severity,
                "description": finding.description,
                "file_path": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
                "root_cause": finding.root_cause,
                "expected_behavior": finding.expected_behavior,
            },
            proposed_code_override=proposed_code_override,
        )

        proposal = RemediationProposal(
            finding_id=finding.id,
            session_id=finding.session_id,
            status=ProposalStatus.AWAITING_APPROVAL.value,
            root_cause_analysis=payload["root_cause_analysis"],
            explanation=payload["explanation"],
            affected_files=payload["affected_files"],
            expected_behavior=payload["expected_behavior"],
            potential_impact=payload["potential_impact"],
            safety_check_results=payload["safety_check_results"],
            test_plan=payload["test_plan"],
            rollback_procedure=payload["rollback_procedure"],
            active_patch_checksum=payload["patch_checksum"],
        )
        db.add(proposal)
        await db.flush()

        diff_evidence = await self.evidence_service.store_evidence(
            db=db,
            session_id=finding.session_id,
            finding_id=finding.id,
            evidence_type=EvidenceType.PATCH_DIFF.value,
            source_tool="RemediationAgent",
            content_text=payload["unified_diff"],
            content_excerpt=payload["unified_diff"][:1500],
            metadata_json={"patch_checksum": payload["patch_checksum"]},
            filename_hint="proposed_patch.diff",
        )

        patch = Patch(
            proposal_id=proposal.id,
            sha256_checksum=payload["patch_checksum"],
            target_file_path=payload["target_file_path"],
            original_code=payload["original_code"],
            proposed_code=payload["proposed_code"],
            unified_diff=payload["unified_diff"],
            diff_artifact_uri=diff_evidence.storage_uri,
            syntax_valid=payload["syntax_valid"],
            static_checks_passed=payload["static_checks_passed"],
        )
        db.add(patch)

        finding.lifecycle_status = FindingLifecycleStatus.AWAITING_APPROVAL.value
        await db.commit()
        await db.refresh(proposal)
        return proposal

    async def approve_proposal(
        self,
        db: AsyncSession,
        proposal_id: UUID,
        patch_checksum: str,
        reviewer_id: UUID | None,
        reviewer_name: str,
        comments: str | None = None,
    ) -> RemediationProposal:
        proposal = await db.get(RemediationProposal, proposal_id)
        if proposal is None:
            raise EntityNotFoundError("RemediationProposal", proposal_id)

        if proposal.active_patch_checksum != patch_checksum:
            raise ApprovalIntegrityError(
                "Approval rejected: provided patch_checksum does not match the proposal's active_patch_checksum.",
                details={
                    "expected_checksum": proposal.active_patch_checksum,
                    "provided_checksum": patch_checksum,
                },
            )

        RemediationApprovalStateMachine.validate_transition(
            ProposalStatus(proposal.status), ProposalStatus.APPROVED
        )
        proposal.status = ProposalStatus.APPROVED.value

        approval = Approval(
            proposal_id=proposal.id,
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
            decision=ApprovalDecision.APPROVED.value,
            approved_patch_checksum=patch_checksum,
            comments=comments,
            is_valid=True,
        )
        db.add(approval)
        db.add(
            AuditEvent(
                session_id=proposal.session_id,
                event_type="REMEDIATION_APPROVED",
                actor=reviewer_name,
                severity="INFO",
                message=f"Proposal {proposal.id} approved with checksum {patch_checksum[:16]}...",
                payload={"proposal_id": str(proposal.id), "patch_checksum": patch_checksum},
            )
        )
        await db.commit()
        await db.refresh(proposal)
        return proposal

    async def reject_proposal(
        self,
        db: AsyncSession,
        proposal_id: UUID,
        patch_checksum: str,
        reviewer_id: UUID | None,
        reviewer_name: str,
        comments: str | None = None,
    ) -> RemediationProposal:
        proposal = await db.get(RemediationProposal, proposal_id)
        if proposal is None:
            raise EntityNotFoundError("RemediationProposal", proposal_id)

        RemediationApprovalStateMachine.validate_transition(
            ProposalStatus(proposal.status), ProposalStatus.REJECTED
        )
        proposal.status = ProposalStatus.REJECTED.value

        approval = Approval(
            proposal_id=proposal.id,
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
            decision=ApprovalDecision.REJECTED.value,
            approved_patch_checksum=patch_checksum,
            comments=comments,
            is_valid=True,
        )
        db.add(approval)

        finding = await db.get(Finding, proposal.finding_id)
        if finding is not None:
            finding.lifecycle_status = FindingLifecycleStatus.NEW.value

        await db.commit()
        await db.refresh(proposal)
        return proposal

    async def apply_approved_patch(
        self,
        db: AsyncSession,
        proposal_id: UUID,
    ) -> RemediationProposal:
        proposal = await db.get(RemediationProposal, proposal_id)
        if proposal is None:
            raise EntityNotFoundError("RemediationProposal", proposal_id)

        finding = await db.get(Finding, proposal.finding_id)
        if finding is None:
            raise EntityNotFoundError("Finding", proposal.finding_id)

        project = await db.get(Project, finding.project_id)
        if project is None:
            raise EntityNotFoundError("Project", finding.project_id)

        patches = list(
            (
                await db.execute(
                    select(Patch)
                    .where(Patch.proposal_id == proposal.id)
                    .order_by(Patch.created_at.desc())
                )
            ).scalars()
        )
        if not patches:
            raise ApprovalIntegrityError("No patch record associated with this proposal.")
        patch = patches[0]

        approvals = list(
            (
                await db.execute(
                    select(Approval)
                    .where(
                        Approval.proposal_id == proposal.id,
                        Approval.decision == ApprovalDecision.APPROVED.value,
                        Approval.is_valid.is_(True),
                    )
                    .order_by(Approval.decided_at.desc())
                )
            ).scalars()
        )
        approved_checksum = approvals[0].approved_patch_checksum if approvals else None

        # Verify recomputed checksum of patch to detect post-approval tampering
        recomputed_checksum = compute_patch_checksum(
            patch.target_file_path, patch.unified_diff
        )
        if recomputed_checksum != patch.sha256_checksum:
            proposal.status = ProposalStatus.INVALIDATED.value
            for ap in approvals:
                ap.is_valid = False
            await db.commit()
            raise ApprovalIntegrityError(
                "Patch content was modified after approval; approval has been invalidated."
            )

        try:
            RemediationApprovalStateMachine.verify_checksum_for_application(
                proposal_status=ProposalStatus(proposal.status),
                active_patch_checksum=proposal.active_patch_checksum,
                approved_patch_checksum=approved_checksum,
            )
        except Exception as exc:
            raise ApprovalIntegrityError(str(exc)) from exc

        # Create isolated remediation working copy so original main branch is recoverable
        settings = get_settings()
        remediation_workspace = (
            settings.workspace_path / f"remediation_{proposal.id}"
        )
        if remediation_workspace.exists():
            shutil.rmtree(remediation_workspace, ignore_errors=True)
        shutil.copytree(
            Path(project.root_path).resolve(),
            remediation_workspace,
            ignore=shutil.ignore_patterns(
                ".git", ".postgres_data", ".qc_storage", ".qc_workspaces", "node_modules", ".venv"
            ),
            dirs_exist_ok=True,
        )

        # Initialize isolated Git branch inside remediation working copy
        branch_name = f"qc-remediation/{str(proposal.id)[:8]}"
        subprocess.run(["git", "init"], cwd=remediation_workspace, capture_output=True, check=False)
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=remediation_workspace,
            capture_output=True,
            check=False,
        )

        target_file_in_ws = (remediation_workspace / patch.target_file_path).resolve()
        target_file_in_ws.parent.mkdir(parents=True, exist_ok=True)

        # Verify source snapshot has not unexpectedly diverged
        if target_file_in_ws.exists():
            current_disk_code = target_file_in_ws.read_text(encoding="utf-8", errors="replace")
            if current_disk_code != patch.original_code:
                proposal.status = ProposalStatus.INVALIDATED.value
                await db.commit()
                raise ApprovalIntegrityError(
                    "Source file snapshot changed since patch was generated; re-propose patch."
                )

        # Apply patch in isolated working branch
        target_file_in_ws.write_text(patch.proposed_code, encoding="utf-8")
        patch.working_branch = branch_name
        patch.applied_at = datetime.now(UTC)
        proposal.status = ProposalStatus.APPLIED.value
        finding.lifecycle_status = FindingLifecycleStatus.PATCH_APPLIED.value
        await db.flush()

        # Run deterministic regression verification on the isolated patched workspace
        ctx = AuditContext(
            session_id=proposal.session_id,
            project_id=project.id,
            project_name=project.name,
            root_path=str(remediation_workspace),
            workspace_path=str(remediation_workspace),
            runner_mode=RunnerMode.LOCAL,
            audit_scope=AuditScope.CODE,
        )
        dummy_task = AuditTaskDTO(
            id=proposal.id,
            task_key="regression_verification",
            agent_type="RemediationVerifier",
            phase="REGRESSION",
            status=TaskStatus.RUNNING,
        )
        cq_res = await CodeQualityAgent().execute(ctx, dummy_task)
        sec_res = await SecurityAuditor().execute(ctx, dummy_task)

        post_findings = cq_res.findings + sec_res.findings
        still_present = any(
            pf.file_path == finding.file_path and pf.category == finding.category
            for pf in post_findings
        )
        syntax_errors = any(str(pf.category) == "SYNTAX_ERROR" for pf in post_findings)

        issue_resolved = (not still_present) and (not syntax_errors) and patch.syntax_valid
        regressions_detected = syntax_errors

        test_run = TestRun(
            session_id=proposal.session_id,
            test_suite_type=TestSuiteType.REGRESSION.value,
            tool_name="RemediationRegressionVerifier",
            command=f"verify_patch --branch {branch_name} --file {patch.target_file_path}",
            status=TestRunStatus.PASSED.value if issue_resolved else TestRunStatus.FAILED.value,
            total_tests=2,
            passed_tests=2 if issue_resolved else 0,
            failed_tests=0 if issue_resolved else 2,
            skipped_tests=0,
            duration_seconds=round(cq_res.duration_seconds + sec_res.duration_seconds, 3),
            exit_code=0 if issue_resolved else 1,
            details={
                "working_branch": branch_name,
                "isolated_workspace": str(remediation_workspace),
                "post_findings_count": len(post_findings),
                "issue_resolved": issue_resolved,
            },
        )
        db.add(test_run)
        await db.flush()

        reg_run = RegressionRun(
            patch_id=patch.id,
            test_run_id=test_run.id,
            status="PASSED" if issue_resolved else "FAILED",
            issue_resolved=issue_resolved,
            regressions_detected=regressions_detected,
            pre_fix_comparison={
                "finding_title": finding.title,
                "category": finding.category,
                "file_path": finding.file_path,
                "status": "CONFIRMED",
            },
            post_fix_comparison={
                "target_defect_present": still_present,
                "syntax_valid": not syntax_errors,
                "remaining_findings_in_file": len(
                    [pf for pf in post_findings if pf.file_path == finding.file_path]
                ),
            },
        )
        db.add(reg_run)

        if issue_resolved:
            proposal.status = ProposalStatus.VERIFIED.value
            finding.lifecycle_status = FindingLifecycleStatus.RESOLVED.value
        else:
            proposal.status = ProposalStatus.FAILED.value
            finding.lifecycle_status = FindingLifecycleStatus.REOPENED.value

        await db.commit()
        await db.refresh(proposal)
        return proposal
