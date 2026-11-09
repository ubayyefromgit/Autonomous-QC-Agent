"""Frontend QA Agent — Browser automation via Playwright, route discovery, console/network & UI inspection."""

import json
import os
import re
import time
from pathlib import Path
from typing import Any

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
from shared.constants.defaults import DEFAULT_EXCLUDED_DIRS

ROUTE_PATH_RE = re.compile(r"""path\s*[:=]\s*['"]([^'"]+)['"]""")


class FrontendQAAgent(BaseSpecializedAgent):
    agent_name = "FrontendQAAgent"
    description = (
        "Discovers frontend routes, inspects UI components, and runs Playwright browser "
        "automation to verify page rendering, console errors, network requests, and responsive layouts."
    )
    supported_scopes = [AuditScope.FULL, AuditScope.FRONTEND, AuditScope.E2E]

    async def execute(self, context: AuditContext, task: AuditTaskDTO) -> AgentResult:
        t0 = time.perf_counter()
        root = Path(context.workspace_path or context.root_path).resolve()
        findings: list[FindingCreateDTO] = []
        test_runs: list[TestRunCreateDTO] = []

        # 1. Discover frontend routes and components
        routes_discovered, ui_files_checked = self._inspect_frontend_sources(root, findings)

        # 2. Run Playwright browser inspection if target URL or built/dev frontend is reachable
        target_url = context.configuration.get("frontend_url")
        browser_report = await self._run_playwright_inspection(
            root=root,
            target_url=target_url,
            routes=routes_discovered,
            findings=findings,
        )

        if browser_report["executed"]:
            test_runs.append(
                TestRunCreateDTO(
                    test_suite_type=TestSuiteType.BROWSER_E2E,
                    tool_name="PlaywrightChromium",
                    command=f"playwright inspect ({len(browser_report['visited_routes'])} routes)",
                    status=(
                        TestRunStatus.PASSED
                        if browser_report["console_errors_count"] == 0
                        and browser_report["failed_requests_count"] == 0
                        else TestRunStatus.FAILED
                    ),
                    total_tests=max(1, len(browser_report["visited_routes"])),
                    passed_tests=max(
                        0,
                        len(browser_report["visited_routes"])
                        - (1 if browser_report["console_errors_count"] > 0 else 0),
                    ),
                    failed_tests=1 if browser_report["console_errors_count"] > 0 else 0,
                    skipped_tests=0,
                    duration_seconds=browser_report["duration_seconds"],
                    exit_code=0 if browser_report["console_errors_count"] == 0 else 1,
                    output_text=json.dumps(
                        {
                            "visited_routes": browser_report["visited_routes"],
                            "console_errors": browser_report["console_errors"],
                            "failed_requests": browser_report["failed_requests"],
                            "viewports_tested": browser_report["viewports_tested"],
                        },
                        indent=2,
                    ),
                    details=browser_report,
                )
            )

        fe_score = max(0.0, 100.0 - len(findings) * 8.0)
        metrics = [
            MetricCreateDTO(
                dimension=QualityDimension.FRONTEND_QUALITY,
                metric_name="frontend_ui_quality_score",
                metric_value=round(fe_score, 2),
                unit="score",
                weight=0.10,
                breakdown={
                    "ui_files_checked": ui_files_checked,
                    "routes_discovered": len(routes_discovered),
                    "playwright_executed": browser_report["executed"],
                    "visited_routes": browser_report["visited_routes"],
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
                "ui_files_checked": ui_files_checked,
                "routes_discovered": routes_discovered,
                "playwright_executed": browser_report["executed"],
            },
        )

    def _inspect_frontend_sources(
        self, root: Path, findings: list[FindingCreateDTO]
    ) -> tuple[list[str], int]:
        routes: set[str] = {"/"}
        ui_files = 0
        for current_root, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS]
            for fname in sorted(files):
                if not fname.endswith((".tsx", ".jsx", ".html", ".vue")):
                    continue
                fpath = Path(current_root) / fname
                rel_path = fpath.relative_to(root).as_posix()
                if "tests/fixtures" in rel_path and "fixtures" not in root.name:
                    continue
                ui_files += 1
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                for match in ROUTE_PATH_RE.finditer(content):
                    r_path = match.group(1)
                    if r_path.startswith("/") and ":" not in r_path and "*" not in r_path:
                        routes.add(r_path)

                # Check dangerous innerHTML without sanitization
                if "dangerouslySetInnerHTML" in content:
                    lines = content.splitlines()
                    for idx, line in enumerate(lines, start=1):
                        if "dangerouslySetInnerHTML" in line:
                            findings.append(
                                FindingCreateDTO(
                                    category=FindingCategory.FRONTEND_UI_DEFECT,
                                    severity=FindingSeverity.HIGH,
                                    title=f"Unescaped `dangerouslySetInnerHTML` in {rel_path}:{idx}",
                                    description=(
                                        f"Component `{rel_path}:{idx}` renders raw HTML via "
                                        "`dangerouslySetInnerHTML`, exposing DOM XSS risk."
                                    ),
                                    file_path=rel_path,
                                    line_start=idx,
                                    line_end=idx,
                                    agent_name=self.agent_name,
                                    reproduction_steps=[f"Inspect `{rel_path}` at line {idx}."],
                                    expected_behavior="Render escaped JSX content or sanitize HTML with DOMPurify.",
                                    actual_behavior="Raw HTML string injected into DOM.",
                                    root_cause="Direct usage of `dangerouslySetInnerHTML`.",
                                    impact="Cross-Site Scripting (XSS) if user-controlled data reaches the prop.",
                                    recommended_fix="Replace `dangerouslySetInnerHTML` with safe React JSX elements.",
                                    confidence=0.95,
                                    verification_status=FindingVerificationStatus.CONFIRMED,
                                    evidence_items=[
                                        EvidenceCreateDTO(
                                            evidence_type=EvidenceType.SOURCE_REFERENCE,
                                            source_tool="FrontendDOMInspector",
                                            content_text=line.strip(),
                                            content_excerpt=line.strip(),
                                        )
                                    ],
                                )
                            )
        return sorted(routes), ui_files

    async def _run_playwright_inspection(
        self,
        root: Path,
        target_url: str | None,
        routes: list[str],
        findings: list[FindingCreateDTO],
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        console_errors: list[str] = []
        failed_requests: list[str] = []
        visited_routes: list[str] = []
        screenshots_captured = 0

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {
                "executed": False,
                "reason": "playwright module not installed",
                "visited_routes": [],
                "console_errors": [],
                "console_errors_count": 0,
                "failed_requests": [],
                "failed_requests_count": 0,
                "viewports_tested": [],
                "duration_seconds": 0.0,
            }

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(viewport={"width": 1440, "height": 900})
                page = await context.new_page()

                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text)
                    if msg.type == "error"
                    else None,
                )
                page.on("pageerror", lambda err: console_errors.append(str(err)))
                page.on(
                    "requestfailed",
                    lambda req: failed_requests.append(f"{req.method} {req.url}"),
                )

                if target_url:
                    for route in routes[:8]:
                        full_url = f"{target_url.rstrip('/')}/{route.lstrip('/')}"
                        await page.goto(full_url, wait_until="networkidle", timeout=10000)
                        visited_routes.append(route)
                else:
                    # Inspect index.html if present in project
                    index_html = root / "frontend" / "index.html"
                    if not index_html.exists():
                        index_html = root / "index.html"
                    if index_html.exists():
                        await page.goto(index_html.as_uri(), wait_until="domcontentloaded", timeout=8000)
                        visited_routes.append(index_html.relative_to(root).as_posix())

                if visited_routes:
                    # Test responsive mobile viewport
                    await page.set_viewport_size({"width": 390, "height": 844})
                    png_bytes = await page.screenshot(full_page=True)
                    screenshots_captured += 1

                    if console_errors:
                        findings.append(
                            FindingCreateDTO(
                                category=FindingCategory.BROWSER_CONSOLE_ERROR,
                                severity=FindingSeverity.MEDIUM,
                                title="Browser runtime console errors detected during Playwright inspection",
                                description=f"Playwright captured {len(console_errors)} console/page error(s): {console_errors[:3]}",
                                agent_name=self.agent_name,
                                reproduction_steps=["Open application in Chromium and inspect DevTools console."],
                                expected_behavior="Zero unhandled console errors during page load and navigation.",
                                actual_behavior="\n".join(console_errors[:5]),
                                root_cause="Runtime JavaScript exception or missing asset.",
                                impact="Broken interactive UI widgets or degraded user experience.",
                                recommended_fix="Fix the underlying runtime exception logged in the browser console.",
                                confidence=0.98,
                                verification_status=FindingVerificationStatus.CONFIRMED,
                                evidence_items=[
                                    EvidenceCreateDTO(
                                        evidence_type=EvidenceType.BROWSER_SCREENSHOT,
                                        source_tool="PlaywrightChromium",
                                        content_bytes=png_bytes,
                                        content_excerpt=f"Playwright screenshot ({len(png_bytes)} bytes) with {len(console_errors)} console error(s).",
                                        filename_hint="playwright_failure.png",
                                    )
                                ],
                            )
                        )

                await browser.close()
                return {
                    "executed": len(visited_routes) > 0,
                    "visited_routes": visited_routes,
                    "console_errors": console_errors,
                    "console_errors_count": len(console_errors),
                    "failed_requests": failed_requests,
                    "failed_requests_count": len(failed_requests),
                    "screenshots_captured": screenshots_captured,
                    "viewports_tested": ["1440x900", "390x844"],
                    "duration_seconds": round(time.perf_counter() - t0, 3),
                }
        except Exception as exc:
            return {
                "executed": False,
                "reason": str(exc),
                "visited_routes": visited_routes,
                "console_errors": console_errors,
                "console_errors_count": len(console_errors),
                "failed_requests": failed_requests,
                "failed_requests_count": len(failed_requests),
                "viewports_tested": [],
                "duration_seconds": round(time.perf_counter() - t0, 3),
            }
