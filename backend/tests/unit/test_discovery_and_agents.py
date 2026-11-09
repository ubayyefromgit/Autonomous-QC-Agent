"""Unit tests for RepositoryIntelligenceEngine, ProjectRunner, and Specialized Agents."""

from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.agents.code_auditor.agent import CodeQualityAgent
from backend.app.agents.performance_auditor.agent import PerformanceAuditor
from backend.app.agents.security_auditor.agent import SecurityAuditor
from backend.app.audit_engine.discovery.repository_intelligence_engine import (
    RepositoryIntelligenceEngine,
)
from backend.app.core.exceptions import SecurityPolicyViolationError
from backend.app.domain.enums.audit_enums import AuditScope, RunnerMode, TaskStatus
from backend.app.domain.interfaces.contracts import AuditContext, AuditTaskDTO
from backend.app.infrastructure.execution.project_runner import (
    DockerProjectRunner,
    LocalProjectRunner,
)


def test_repository_intelligence_discovery_and_coverage(tmp_path: Path) -> None:
    # Create a mixed-stack repository structure
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("console.log(1);", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi>=0.110.0\nsqlalchemy>=2.0\npytest\n", encoding="utf-8")
    (tmp_path / "backend" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    (tmp_path / "frontend" / "package.json").write_text(
        '{"dependencies": {"react": "^18.2.0", "vite": "^5.0.0", "tailwindcss": "^3.4.0"}}',
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "App.tsx").write_text(
        "export default function App() { return <div>Hello</div>; }\n",
        encoding="utf-8",
    )

    engine = RepositoryIntelligenceEngine()
    res = engine.discover_repository(tmp_path)
    manifest = res["manifest"]

    assert "Python" in manifest["languages"]
    assert "TypeScript" in manifest["languages"]
    assert "FastAPI" in manifest["frameworks"]
    assert "React" in manifest["frameworks"]
    assert manifest["backend"]["detected"] is True
    assert manifest["frontend"]["detected"] is True
    assert manifest["coverage"]["files_excluded"] >= 1
    assert manifest["coverage"]["inspection_coverage_percent"] == 100.0


@pytest.mark.asyncio
async def test_runners_and_security_command_policy(tmp_path: Path) -> None:
    (tmp_path / "hello.py").write_text("print('sandbox-ok')\n", encoding="utf-8")
    runner = LocalProjectRunner(workspace_root=tmp_path / "workspaces")
    session_id = uuid4()
    ws = await runner.prepare_workspace(tmp_path, session_id)

    try:
        snap = await runner.verify_snapshot(ws)
        assert snap["verified"] is True
        assert ws.synthetic_env_path.exists()

        exec_res = await runner.execute_command(ws, ["python", "hello.py"], timeout=10)
        assert exec_res.exit_code == 0
        assert "sandbox-ok" in exec_res.stdout

        # Disallowed command must raise SecurityPolicyViolationError
        with pytest.raises(SecurityPolicyViolationError):
            await runner.execute_command(ws, ["powershell", "-Command", "Get-Process"])

        # Docker runner command builder must enforce non-root and never mount docker.sock
        docker_runner = DockerProjectRunner()
        docker_args = docker_runner.build_docker_run_args(ws, ["pytest", "-q"])
        assert "--user" in docker_args
        assert "10001:10001" in docker_args
        assert "--cap-drop=ALL" in docker_args
        assert "--read-only" in docker_args
        assert all("docker.sock" not in a for a in docker_args)
    finally:
        await runner.cleanup(ws)


@pytest.mark.asyncio
async def test_specialized_agents_detect_real_defects_with_evidence(tmp_path: Path) -> None:
    defective_py = tmp_path / "service.py"
    defective_py.write_text(
        """import time

API_SECRET = "super_secret_prod_token_987654321"

def add_item(item, bucket=[]):
    try:
        bucket.append(item)
        return eval("1 + 1")
        print("unreachable dead code")
    except:
        pass

async def slow_endpoint(user_id: str, db):
    time.sleep(0.1)
    db.execute(f"SELECT * FROM users WHERE id = '{user_id}'")
""",
        encoding="utf-8",
    )

    ctx = AuditContext(
        session_id=uuid4(),
        project_id=uuid4(),
        project_name="defective-fixture",
        root_path=str(tmp_path),
        workspace_path=str(tmp_path),
        runner_mode=RunnerMode.LOCAL,
        audit_scope=AuditScope.FULL,
    )
    task = AuditTaskDTO(
        id=uuid4(),
        task_key="test_task",
        agent_type="CodeQualityAgent",
        phase="STATIC",
        status=TaskStatus.RUNNING,
    )

    cq_res = await CodeQualityAgent().execute(ctx, task)
    sec_res = await SecurityAuditor().execute(ctx, task)
    perf_res = await PerformanceAuditor().execute(ctx, task)

    cq_titles = [f.title for f in cq_res.findings]
    assert any("Mutable default argument" in t for t in cq_titles)
    assert any("Unreachable dead code" in t for t in cq_titles)
    assert any("Bare `except:`" in t for t in cq_titles)
    assert all(len(f.evidence_items) > 0 for f in cq_res.findings)

    sec_titles = [f.title for f in sec_res.findings]
    assert any("Hardcoded" in t for t in sec_titles)
    assert any("SQL Injection" in t for t in sec_titles)
    assert any("eval()" in t for t in sec_titles)
    assert all(len(f.evidence_items) > 0 for f in sec_res.findings)

    perf_titles = [f.title for f in perf_res.findings]
    assert any("time.sleep()" in t for t in perf_titles)
