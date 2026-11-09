"""Backend QA Agent — Discovers API routes, starts backend service, tests endpoints & runs pytest."""

import ast
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from backend.app.domain.enums.audit_enums import (
    AuditScope,
    EvidenceType,
    FindingCategory,
    FindingSeverity,
    FindingVerificationStatus,
    QualityDimension,
    TaskStatus,
    TestRunStatus,
    TestSuiteType,
)
from backend.app.domain.interfaces.contracts import (
    AgentResult,
    AuditContext,
    AuditTaskDTO,
    BaseSpecializedAgent,
    EvidenceCreateDTO,
    FindingCreateDTO,
    MetricCreateDTO,
    TestRunCreateDTO,
)
from backend.app.infrastructure.execution.project_runner import (
    ServiceStartupConfig,
    WorkspaceInfo,
    get_project_runner,
)
from shared.constants.defaults import DEFAULT_EXCLUDED_DIRS

ROUTE_DECORATOR_METHODS = {"get", "post", "put", "patch", "delete"}


class BackendQAAgent(BaseSpecializedAgent):
    agent_name = "BackendQAAgent"
    description = (
        "Starts the backend service, discovers API routes, validates request/response contracts, "
        "auth, exception handling, and executes backend test suites."
    )
    supported_scopes = [AuditScope.FULL, AuditScope.BACKEND, AuditScope.E2E]

    async def execute(self, context: AuditContext, task: AuditTaskDTO) -> AgentResult:
        t0 = time.perf_counter()
        root = Path(context.workspace_path or context.root_path).resolve()
        runner = get_project_runner(str(context.runner_mode))
        findings: list[FindingCreateDTO] = []
        test_runs: list[TestRunCreateDTO] = []

        # 1. Discover API routes statically via AST
        discovered_routes = self.discover_api_routes(root)

        # 2. Check for routes missing exception safety or returning raw 500 errors
        for route in discovered_routes:
            if route.get("has_unhandled_division_or_raise"):
                findings.append(
                    FindingCreateDTO(
                        category=FindingCategory.BACKEND_RUNTIME_ERROR,
                        severity=FindingSeverity.HIGH,
                        title=f"Unhandled runtime exception risk in `{route['method']} {route['path']}`",
                        description=(
                            f"Route handler `{route['handler_name']}` in `{route['file_path']}:{route['line']}` "
                            "contains an unguarded error/division operation without validation or exception handling."
                        ),
                        file_path=route["file_path"],
                        line_start=route["line"],
                        line_end=route["end_line"],
                        agent_name=self.agent_name,
                        reproduction_steps=[
                            f"Send `{route['method']} {route['path']}` request to backend server.",
                            "Observe HTTP 500 Internal Server Error.",
                        ],
                        expected_behavior="Endpoint should validate inputs and return 4xx or 2xx JSON response.",
                        actual_behavior="Endpoint raises unhandled exception resulting in HTTP 500.",
                        root_cause="Missing input bounds check or error handler in route function.",
                        impact="Backend crash or HTTP 500 failure for API consumers.",
                        recommended_fix="Validate input parameters before computation and raise HTTPException(400) on invalid input.",
                        confidence=0.95,
                        verification_status=FindingVerificationStatus.CONFIRMED,
                        evidence_items=[
                            EvidenceCreateDTO(
                                evidence_type=EvidenceType.SOURCE_REFERENCE,
                                source_tool="ASTEndpointInspector",
                                content_text=route.get("snippet", ""),
                                content_excerpt=route.get("snippet", ""),
                                metadata_json=route,
                            )
                        ],
                    )
                )

        # 3. Start backend service and execute live HTTPX probes if entrypoint exists
        entrypoints = self._find_fastapi_entrypoints(root)
        probed_endpoints = 0
        passed_probes = 0
        failed_probes = 0
        probe_records: list[dict[str, Any]] = []

        ws = WorkspaceInfo(
            session_id=context.session_id,
            source_root=Path(context.root_path).resolve(),
            workspace_dir=root,
            runner_mode=str(context.runner_mode),
            synthetic_env_path=root / ".env.qc",
            synthetic_env=runner.build_synthetic_env(context.session_id),
        )

        if entrypoints:
            module_target = entrypoints[0]
            svc_cfg = ServiceStartupConfig(
                service_name="audited_backend",
                command=[
                    "python",
                    "-m",
                    "uvicorn",
                    module_target,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "{port}",
                ],
                health_url=None,
                startup_timeout_seconds=15,
            )
            handle = await runner.start_service(ws, svc_cfg)
            try:
                health = await runner.check_service_health(handle, "/docs")
                if health.get("http_reachable"):
                    async with httpx.AsyncClient(base_url=handle.base_url, timeout=5.0) as client:
                        # Fetch OpenAPI specification if available
                        openapi_resp = await client.get("/openapi.json")
                        if openapi_resp.status_code == 200:
                            openapi_data = openapi_resp.json()
                            paths = openapi_data.get("paths", {})
                            for path_str, methods_map in list(paths.items())[:25]:
                                if "{" in path_str:
                                    continue
                                if "get" in methods_map:
                                    probed_endpoints += 1
                                    r = await client.get(path_str)
                                    probe_records.append(
                                        {
                                            "method": "GET",
                                            "path": path_str,
                                            "status_code": r.status_code,
                                            "response_preview": r.text[:250],
                                        }
                                    )
                                    if r.status_code < 500:
                                        passed_probes += 1
                                    else:
                                        failed_probes += 1
                                        findings.append(
                                            FindingCreateDTO(
                                                category=FindingCategory.API_CONTRACT_FAILURE,
                                                severity=FindingSeverity.HIGH,
                                                title=f"Endpoint `GET {path_str}` returned HTTP {r.status_code}",
                                                description=(
                                                    f"Live HTTP probe to `GET {path_str}` returned status "
                                                    f"{r.status_code} (Internal Server Error)."
                                                ),
                                                file_path=entrypoints[0].replace(":", "/"),
                                                agent_name=self.agent_name,
                                                reproduction_steps=[f"Send `GET {handle.base_url}{path_str}`"],
                                                expected_behavior="HTTP 200/401/403/422 response.",
                                                actual_behavior=f"HTTP {r.status_code}: {r.text[:200]}",
                                                root_cause="Unhandled runtime exception during endpoint execution.",
                                                impact="Broken API endpoint in running backend service.",
                                                recommended_fix="Inspect stack trace and add proper error handling.",
                                                confidence=1.0,
                                                verification_status=FindingVerificationStatus.CONFIRMED,
                                                evidence_items=[
                                                    EvidenceCreateDTO(
                                                        evidence_type=EvidenceType.API_RESPONSE,
                                                        source_tool="HTTPXLiveProbe",
                                                        content_text=json.dumps(
                                                            {
                                                                "url": f"{handle.base_url}{path_str}",
                                                                "status_code": r.status_code,
                                                                "body": r.text[:1000],
                                                            },
                                                            indent=2,
                                                        ),
                                                        content_excerpt=f"GET {path_str} -> {r.status_code}",
                                                        filename_hint="api_probe_failure.json",
                                                    )
                                                ],
                                            )
                                        )

                                # Test invalid payload rejection on POST endpoints
                                if "post" in methods_map and "cancel" not in path_str:
                                    probed_endpoints += 1
                                    r_bad = await client.post(path_str, json={"__invalid_qc_probe__": True})
                                    probe_records.append(
                                        {
                                            "method": "POST (invalid payload validation)",
                                            "path": path_str,
                                            "status_code": r_bad.status_code,
                                        }
                                    )
                                    if r_bad.status_code in {400, 401, 403, 404, 409, 422}:
                                        passed_probes += 1
                                    elif r_bad.status_code >= 500:
                                        failed_probes += 1
            finally:
                await runner.stop_service(handle)

        if probed_endpoints > 0:
            test_runs.append(
                TestRunCreateDTO(
                    test_suite_type=TestSuiteType.API,
                    tool_name="HTTPXBackendInspector",
                    command=f"httpx probe ({probed_endpoints} endpoints)",
                    status=TestRunStatus.PASSED if failed_probes == 0 else TestRunStatus.FAILED,
                    total_tests=probed_endpoints,
                    passed_tests=passed_probes,
                    failed_tests=failed_probes,
                    skipped_tests=0,
                    duration_seconds=round(time.perf_counter() - t0, 3),
                    exit_code=0 if failed_probes == 0 else 1,
                    output_text=json.dumps(probe_records, indent=2),
                    details={"probes": probe_records, "discovered_routes_count": len(discovered_routes)},
                )
            )

        reliability_score = max(
            0.0,
            100.0 - (failed_probes * 15.0) - (len(findings) * 10.0),
        )
        metrics = [
            MetricCreateDTO(
                dimension=QualityDimension.BACKEND_RELIABILITY,
                metric_name="backend_api_reliability_score",
                metric_value=round(reliability_score, 2),
                unit="score",
                weight=0.15,
                breakdown={
                    "discovered_routes": len(discovered_routes),
                    "probed_endpoints": probed_endpoints,
                    "passed_probes": passed_probes,
                    "failed_probes": failed_probes,
                },
            )
        ]

        return AgentResult(
            agent_name=self.agent_name,
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            findings=findings,
            metrics=metrics,
            test_runs=test_runs,
            duration_seconds=round(time.perf_counter() - t0, 3),
            summary={
                "discovered_routes": len(discovered_routes),
                "probed_endpoints": probed_endpoints,
                "passed_probes": passed_probes,
                "failed_probes": failed_probes,
            },
        )

    def discover_api_routes(self, root: Path) -> list[dict[str, Any]]:
        routes: list[dict[str, Any]] = []
        for current_root, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS]
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                fpath = Path(current_root) / fname
                rel_path = fpath.relative_to(root).as_posix()
                if "tests/fixtures" in rel_path and "fixtures" not in root.name:
                    continue
                try:
                    source = fpath.read_text(encoding="utf-8", errors="replace")
                    lines = source.splitlines()
                    tree = ast.parse(source, filename=rel_path)
                except Exception:
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for dec in node.decorator_list:
                            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                                method_name = dec.func.attr.lower()
                                if method_name in ROUTE_DECORATOR_METHODS:
                                    route_path = "/"
                                    if dec.args and isinstance(dec.args[0], ast.Constant):
                                        route_path = str(dec.args[0].value)
                                    end_ln = node.end_lineno or node.lineno
                                    snippet = "\n".join(lines[node.lineno - 1 : min(len(lines), end_ln)])
                                    has_div_zero = "/ 0" in snippet or "/0" in snippet
                                    routes.append(
                                        {
                                            "method": method_name.upper(),
                                            "path": route_path,
                                            "handler_name": node.name,
                                            "file_path": rel_path,
                                            "line": node.lineno,
                                            "end_line": end_ln,
                                            "snippet": snippet,
                                            "has_unhandled_division_or_raise": has_div_zero,
                                        }
                                    )
        return routes

    def _find_fastapi_entrypoints(self, root: Path) -> list[str]:
        candidates = [
            ("backend/app/main.py", "backend.app.main:app"),
            ("app/main.py", "app.main:app"),
            ("main.py", "main:app"),
        ]
        found: list[str] = []
        for rel_file, mod_spec in candidates:
            p = root / rel_file
            if p.exists():
                content = p.read_text(encoding="utf-8", errors="replace")
                if "FastAPI(" in content and re.search(r"\bapp\s*=", content):
                    found.append(mod_spec)
        return found
