"""Architecture Auditor — Evaluates SOLID principles, separation of concerns, circular dependencies & coupling."""

import ast
import json
import os
import time
from pathlib import Path

from backend.app.domain.enums.audit_enums import (
    AuditScope,
    EvidenceType,
    FindingCategory,
    FindingSeverity,
    FindingVerificationStatus,
    QualityDimension,
    TaskStatus,
)
from backend.app.domain.interfaces.contracts import (
    AgentResult,
    AuditContext,
    AuditTaskDTO,
    BaseSpecializedAgent,
    EvidenceCreateDTO,
    FindingCreateDTO,
    MetricCreateDTO,
)
from shared.constants.defaults import DEFAULT_EXCLUDED_DIRS


class ArchitectureAuditor(BaseSpecializedAgent):
    agent_name = "ArchitectureAuditor"
    description = (
        "Evaluates SOLID principles, separation of concerns, circular dependencies, "
        "module coupling, and architectural layer violations."
    )
    supported_scopes = [AuditScope.FULL, AuditScope.CODE]

    async def execute(self, context: AuditContext, task: AuditTaskDTO) -> AgentResult:
        t0 = time.perf_counter()
        root = Path(context.workspace_path or context.root_path).resolve()
        findings: list[FindingCreateDTO] = []

        dep_graph: dict[str, list[str]] = context.manifest.get("dependency_graph", {})
        # 1. Detect circular dependencies
        cycles = self._detect_import_cycles(dep_graph)
        for cycle in cycles[:5]:
            cycle_str = " -> ".join(cycle)
            findings.append(
                FindingCreateDTO(
                    category=FindingCategory.CIRCULAR_DEPENDENCY,
                    severity=FindingSeverity.HIGH,
                    title=f"Circular module dependency detected: {cycle[0]}",
                    description=f"A circular import cycle was detected across modules: `{cycle_str}`.",
                    file_path=cycle[0],
                    line_start=1,
                    line_end=20,
                    agent_name=self.agent_name,
                    reproduction_steps=[f"Trace import chain: {cycle_str}"],
                    expected_behavior="Module dependency graph must be a Directed Acyclic Graph (DAG).",
                    actual_behavior=f"Cycle found: {cycle_str}",
                    root_cause="Tight bidirectional coupling between modules.",
                    impact="Import-time failures, brittle initialization order, and poor modularity.",
                    recommended_fix="Extract shared interfaces or DTOs into a lower-level domain/shared module.",
                    confidence=0.95,
                    verification_status=FindingVerificationStatus.CONFIRMED,
                    evidence_items=[
                        EvidenceCreateDTO(
                            evidence_type=EvidenceType.SCANNER_REPORT,
                            source_tool="DependencyGraphAnalyzer",
                            content_text=json.dumps({"cycle": cycle}, indent=2),
                            content_excerpt=f"Circular dependency chain: {cycle_str}",
                            filename_hint="circular_dependency.json",
                        )
                    ],
                )
            )

        # 2. Check Clean Architecture layer boundaries and God classes
        total_modules = 0
        max_fan_out = 0
        for current_root, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS]
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                fpath = Path(current_root) / fname
                rel_path = fpath.relative_to(root).as_posix()
                if "tests/fixtures" in rel_path and "fixtures" not in root.name:
                    continue
                total_modules += 1
                try:
                    source = fpath.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source, filename=rel_path)
                except Exception:
                    continue

                imports = [
                    node.module
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module
                ]
                max_fan_out = max(max_fan_out, len(imports))

                # Domain layer must not import FastAPI transport layer
                if "/domain/" in f"/{rel_path}":
                    illegal = [m for m in imports if "fastapi" in m or ".api." in m]
                    if illegal:
                        findings.append(
                            FindingCreateDTO(
                                category=FindingCategory.ARCHITECTURE_VIOLATION,
                                severity=FindingSeverity.HIGH,
                                title=f"Domain layer imports transport layer in {rel_path}",
                                description=(
                                    f"Domain module `{rel_path}` imports transport/API dependencies: "
                                    f"{', '.join(illegal)}."
                                ),
                                file_path=rel_path,
                                line_start=1,
                                line_end=15,
                                agent_name=self.agent_name,
                                reproduction_steps=[f"Inspect imports at top of `{rel_path}`"],
                                expected_behavior="Domain layer must remain independent of HTTP/API frameworks.",
                                actual_behavior=f"Domain module imports {', '.join(illegal)}.",
                                root_cause="Violation of Clean Architecture inward dependency rule.",
                                impact="Couples core business rules to web transport framework.",
                                recommended_fix="Move HTTP-specific logic into `api/` or `application/` layer.",
                                confidence=0.98,
                                verification_status=FindingVerificationStatus.CONFIRMED,
                                evidence_items=[
                                    EvidenceCreateDTO(
                                        evidence_type=EvidenceType.SOURCE_REFERENCE,
                                        source_tool="CleanArchitectureValidator",
                                        content_text="\n".join(source.splitlines()[:25]),
                                        content_excerpt=f"Illegal imports in {rel_path}: {illegal}",
                                    )
                                ],
                            )
                        )

                # Check Single Responsibility Principle (God classes > 30 methods)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        methods = [
                            n
                            for n in node.body
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        ]
                        if len(methods) > 30:
                            findings.append(
                                FindingCreateDTO(
                                    category=FindingCategory.ARCHITECTURE_VIOLATION,
                                    severity=FindingSeverity.MEDIUM,
                                    title=f"SRP violation: Class `{node.name}` defines {len(methods)} methods",
                                    description=(
                                        f"Class `{node.name}` in `{rel_path}` defines {len(methods)} methods, "
                                        "indicating excessive responsibilities (God Class)."
                                    ),
                                    file_path=rel_path,
                                    line_start=node.lineno,
                                    line_end=node.end_lineno or node.lineno,
                                    agent_name=self.agent_name,
                                    reproduction_steps=[f"Count methods on `{node.name}` in `{rel_path}`"],
                                    expected_behavior="Classes should adhere to the Single Responsibility Principle.",
                                    actual_behavior=f"`{node.name}` contains {len(methods)} methods.",
                                    root_cause="Accumulation of unrelated responsibilities in one class.",
                                    impact="High coupling and difficult unit testing.",
                                    recommended_fix="Decompose class into focused, single-purpose services.",
                                    confidence=0.90,
                                    verification_status=FindingVerificationStatus.CONFIRMED,
                                    evidence_items=[
                                        EvidenceCreateDTO(
                                            evidence_type=EvidenceType.SOURCE_REFERENCE,
                                            source_tool="SOLIDArchitectureScanner",
                                            content_text=f"Class {node.name} methods: {[m.name for m in methods]}",
                                            content_excerpt=f"{len(methods)} methods in {node.name}",
                                        )
                                    ],
                                )
                            )

        arch_score = max(0.0, 100.0 - len(findings) * 8.0)
        metrics = [
            MetricCreateDTO(
                dimension=QualityDimension.ARCHITECTURE,
                metric_name="architecture_modularity_score",
                metric_value=round(arch_score, 2),
                unit="score",
                weight=0.10,
                breakdown={
                    "total_modules_analyzed": total_modules,
                    "circular_dependencies_found": len(cycles),
                    "max_module_fan_out": max_fan_out,
                    "architecture_findings": len(findings),
                },
            )
        ]

        return AgentResult(
            agent_name=self.agent_name,
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            findings=findings,
            metrics=metrics,
            duration_seconds=round(time.perf_counter() - t0, 3),
            summary={
                "modules_analyzed": total_modules,
                "cycles_detected": len(cycles),
                "findings_count": len(findings),
            },
        )

    def _detect_import_cycles(self, dep_graph: dict[str, list[str]]) -> list[list[str]]:
        module_to_file: dict[str, str] = {}
        for rel_path in dep_graph:
            if rel_path.endswith(".py"):
                dotted = rel_path[:-3].replace("/", ".")
                module_to_file[dotted] = rel_path

        adj: dict[str, list[str]] = {}
        for rel_path, imported_mods in dep_graph.items():
            adj[rel_path] = []
            for mod in imported_mods:
                target = module_to_file.get(mod)
                if target and target != rel_path:
                    adj[rel_path].append(target)

        visited: set[str] = set()
        stack: list[str] = []
        on_stack: set[str] = set()
        cycles: list[list[str]] = []

        def dfs(node: str) -> None:
            visited.add(node)
            stack.append(node)
            on_stack.add(node)
            for nxt in adj.get(node, []):
                if nxt not in visited:
                    dfs(nxt)
                elif nxt in on_stack:
                    idx = stack.index(nxt)
                    cycles.append(stack[idx:] + [nxt])
            stack.pop()
            on_stack.remove(node)

        for n in list(adj.keys()):
            if n not in visited:
                dfs(n)
        return cycles
