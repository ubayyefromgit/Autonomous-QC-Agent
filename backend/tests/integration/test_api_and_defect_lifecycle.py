"""End-to-End Integration tests for REST API v1, PostgreSQL persistence, and full Defect Remediation Lifecycle."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_full_api_and_defect_remediation_lifecycle(tmp_path: Path) -> None:
    # 1. Create controlled defective fixture project in isolated tmp_path
    fixture_dir = tmp_path / "vulnerable_fixture_app"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "requirements.txt").write_text("fastapi>=0.110.0\n", encoding="utf-8")
    (fixture_dir / "calculator.py").write_text(
        """def compute_discount(price: float, items=[]):
    try:
        items.append(price)
        return eval("price * 0.9")
    except:
        return price
""",
        encoding="utf-8",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 2. Verify System Health & Executors
        health_resp = await client.get("/api/v1/system/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data["status"] == "HEALTHY"
        assert health_data["database"]["connected"] is True

        agents_resp = await client.get("/api/v1/system/agents")
        assert agents_resp.status_code == 200
        assert agents_resp.json()["total_registered"] == 10

        exec_resp = await client.get("/api/v1/system/executors")
        assert exec_resp.status_code == 200

        # 3. Register Project
        proj_resp = await client.post(
            "/api/v1/projects",
            json={
                "name": "Controlled Defective Fixture App",
                "description": "Isolated fixture for end-to-end defect lifecycle validation",
                "root_path": str(fixture_dir),
                "execution_mode": "LOCAL",
            },
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        # 4. Run Repository Discovery
        disc_resp = await client.post(f"/api/v1/projects/{project_id}/discover")
        assert disc_resp.status_code == 200
        manifest = disc_resp.json()["manifest"]
        assert "Python" in manifest["languages"]
        assert manifest["coverage"]["inspection_coverage_percent"] == 100.0

        files_resp = await client.get(f"/api/v1/projects/{project_id}/files")
        assert files_resp.status_code == 200
        assert len(files_resp.json()) >= 2

        # 5. Execute Full Synchronous Audit against the Fixture
        audit_resp = await client.post(
            f"/api/v1/projects/{project_id}/audits",
            json={
                "audit_scope": "FULL",
                "runner_mode": "LOCAL",
                "run_immediately": True,
                "run_synchronously": True,
            },
        )
        assert audit_resp.status_code == 201
        audit_data = audit_resp.json()
        audit_id = audit_data["id"]
        assert audit_data["status"] == "COMPLETED"
        # Because eval() is a CRITICAL confirmed security finding, release_gate MUST be REJECTED
        assert audit_data["release_gate"] == "REJECTED"

        # 6. Check Progress & Findings
        prog_resp = await client.get(f"/api/v1/audits/{audit_id}/progress")
        assert prog_resp.status_code == 200
        assert prog_resp.json()["progress_percent"] == 100.0

        findings_resp = await client.get(f"/api/v1/audits/{audit_id}/findings")
        assert findings_resp.status_code == 200
        findings = findings_resp.json()
        assert len(findings) >= 3

        # Pick the eval() security finding or bare except finding in calculator.py
        eval_finding = next(
            f for f in findings if "eval()" in f["title"] or f["file_path"] == "calculator.py"
        )
        finding_id = eval_finding["id"]
        assert eval_finding["verification_status"] == "CONFIRMED"
        assert eval_finding["evidence_count"] >= 1

        # Verify Evidence retrieval
        ev_resp = await client.get(f"/api/v1/findings/{finding_id}/evidence")
        assert ev_resp.status_code == 200
        assert len(ev_resp.json()) >= 1

        # 7. Generate Remediation Proposal (with clean fixed code for calculator.py)
        clean_code = """def compute_discount(price: float, items=None):
    if items is None:
        items = []
    try:
        items.append(price)
        return price * 0.9
    except Exception:
        return price
"""
        prop_resp = await client.post(
            f"/api/v1/findings/{finding_id}/proposals",
            json={"proposed_code_override": clean_code},
        )
        assert prop_resp.status_code == 201
        proposal = prop_resp.json()
        proposal_id = proposal["id"]
        patch_checksum = proposal["active_patch_checksum"]
        assert proposal["status"] == "AWAITING_APPROVAL"
        assert len(proposal["patches"]) == 1
        assert "--- a/calculator.py" in proposal["patches"][0]["unified_diff"]

        # 8. Attempt to apply BEFORE human approval -> MUST fail with 409
        premature_apply = await client.post(f"/api/v1/remediation/{proposal_id}/apply")
        assert premature_apply.status_code == 409

        # 9. Attempt to approve with WRONG checksum -> MUST fail with 409
        bad_approve = await client.post(
            f"/api/v1/remediation/{proposal_id}/approve",
            json={
                "patch_checksum": "0000000000000000000000000000000000000000000000000000000000000000",
                "reviewer_name": "Security Lead",
                "comments": "Mismatched checksum test",
            },
        )
        assert bad_approve.status_code == 409

        # 10. Approve with exact SHA-256 patch_checksum
        good_approve = await client.post(
            f"/api/v1/remediation/{proposal_id}/approve",
            json={
                "patch_checksum": patch_checksum,
                "reviewer_name": "Principal Security Architect",
                "comments": "Verified diff and approved for isolated branch application.",
            },
        )
        assert good_approve.status_code == 200
        assert good_approve.json()["status"] == "APPROVED"

        # 11. Apply approved patch in isolated working branch & run automated Regression Verification
        apply_resp = await client.post(f"/api/v1/remediation/{proposal_id}/apply")
        assert apply_resp.status_code == 200
        applied_data = apply_resp.json()
        assert applied_data["status"] == "VERIFIED"
        assert len(applied_data["regression_runs"]) == 1
        assert applied_data["regression_runs"][0]["issue_resolved"] is True

        # 12. Verify Finding lifecycle status is now RESOLVED and original file was NOT mutated directly
        updated_finding_resp = await client.get(f"/api/v1/findings/{finding_id}")
        assert updated_finding_resp.status_code == 200
        assert updated_finding_resp.json()["lifecycle_status"] == "RESOLVED"
        assert 'eval("price * 0.9")' in (fixture_dir / "calculator.py").read_text(encoding="utf-8")

        # 13. Generate HTML and PDF Audit Reports
        pdf_rep_resp = await client.post(
            f"/api/v1/audits/{audit_id}/reports",
            json={"report_format": "PDF"},
        )
        assert pdf_rep_resp.status_code == 201
        pdf_report_id = pdf_rep_resp.json()["id"]

        dl_resp = await client.get(f"/api/v1/reports/{pdf_report_id}/download")
        assert dl_resp.status_code == 200
        assert dl_resp.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_upload_zip_runtime_config_and_readiness_advisor() -> None:
    """Verify ZIP upload, runtime API key configuration, and project readiness advisor endpoints."""
    import io
    import zipfile

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Runtime configuration & instructions endpoint
        rc_resp = await client.get("/api/v1/system/runtime-config")
        assert rc_resp.status_code == 200
        rc_data = rc_resp.json()
        assert "ai_config" in rc_data
        assert "system_tools" in rc_data
        assert "instructions" in rc_data
        assert len(rc_data["instructions"]["quick_start_steps"]) >= 4

        # 2. Create an in-memory ZIP archive with a sample Python project and .env.example
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("sample_app/main.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
            zf.writestr("sample_app/requirements.txt", "fastapi>=0.110.0\n")
            zf.writestr("sample_app/.env.example", "CUSTOM_API_SECRET=replace-with-your-secret\n")
        buf.seek(0)

        upload_resp = await client.post(
            "/api/v1/projects/upload-zip",
            data={
                "name": "Uploaded ZIP Sample App",
                "description": "Integration test ZIP upload",
                "execution_mode": "LOCAL",
            },
            files={"file": ("sample_app.zip", buf.getvalue(), "application/zip")},
        )
        assert upload_resp.status_code == 201, upload_resp.text
        uploaded_project = upload_resp.json()
        proj_id = uploaded_project["id"]

        # 3. Check project readiness advisor
        readiness_resp = await client.get(f"/api/v1/projects/{proj_id}/readiness")
        assert readiness_resp.status_code == 200
        r_data = readiness_resp.json()
        assert r_data["ready_to_audit"] is True
        assert "CUSTOM_API_SECRET" in r_data["missing_env_keys"]
        assert len(r_data["checklist"]) >= 3

        # 4. Save target project .env variable via endpoint and re-verify readiness
        env_save_resp = await client.post(
            f"/api/v1/projects/{proj_id}/env",
            json={"env_content": "CUSTOM_API_SECRET=configured_value_123"},
        )
        assert env_save_resp.status_code == 200
        readiness_after = (await client.get(f"/api/v1/projects/{proj_id}/readiness")).json()
        assert "CUSTOM_API_SECRET" not in readiness_after["missing_env_keys"]
