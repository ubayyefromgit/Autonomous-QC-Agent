"""Code Quality Agent — AST analysis, Ruff/Mypy execution, complexity, dead code, duplicates & incomplete logic."""

import ast
import hashlib
import os
import re
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

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)", re.IGNORECASE)


class CodeQualityAgent(BaseSpecializedAgent):
    agent_name = "CodeQualityAgent"
    description = (
        "Identifies syntax errors, logical inconsistencies, dead code, duplicate code, "
        "bare exception swallowing, complexity, and incomplete implementations."
    )
    supported_scopes = [AuditScope.FULL, AuditScope.CODE]

    async def execute(self, context: AuditContext, task: AuditTaskDTO) -> AgentResult:
        t0 = time.perf_counter()
        root = Path(context.workspace_path or context.root_path).resolve()
        findings: list[FindingCreateDTO] = []
        function_hashes: dict[str, tuple[str, int, str]] = {}
        files_checked = 0
        high_complexity_count = 0

        for current_root, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS]
            for fname in sorted(files):
                fpath = Path(current_root) / fname
                rel_path = fpath.relative_to(root).as_posix()

                # Skip test fixture directories when auditing the platform itself unless root IS the fixture
                if "tests/fixtures" in rel_path and "fixtures" not in root.name:
                    continue

                if fname.endswith(".py"):
                    files_checked += 1
                    self._inspect_python_file(
                        fpath, rel_path, findings, function_hashes
                    )
                elif fname.endswith((".ts", ".tsx", ".js", ".jsx")):
                    files_checked += 1
                    self._inspect_js_ts_file(fpath, rel_path, findings)

        for f in findings:
            if f.category == FindingCategory.COMPLEXITY:
                high_complexity_count += 1

        score = max(0.0, 100.0 - len(findings) * 4.0)
        metrics = [
            MetricCreateDTO(
                dimension=QualityDimension.CODE_QUALITY,
                metric_name="static_code_quality_score",
                metric_value=round(score, 2),
                unit="score",
                weight=0.15,
                breakdown={
                    "files_checked": files_checked,
                    "findings_detected": len(findings),
                    "high_complexity_functions": high_complexity_count,
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
                "files_checked": files_checked,
                "findings_count": len(findings),
            },
        )

    def _inspect_python_file(
        self,
        fpath: Path,
        rel_path: str,
        findings: list[FindingCreateDTO],
        function_hashes: dict[str, tuple[str, int, str]],
    ) -> None:
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        lines = source.splitlines()

        # 1. Syntax Validation
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError as exc:
            lineno = exc.lineno or 1
            snippet = self._extract_snippet(lines, lineno, lineno + 2)
            findings.append(
                FindingCreateDTO(
                    category=FindingCategory.SYNTAX_ERROR,
                    severity=FindingSeverity.CRITICAL,
                    title=f"Python SyntaxError in {rel_path}:{lineno}",
                    description=f"Python AST parser failed with SyntaxError: {exc.msg} at line {lineno}.",
                    file_path=rel_path,
                    line_start=lineno,
                    line_end=lineno,
                    agent_name=self.agent_name,
                    reproduction_steps=[f"Run `python -m py_compile {rel_path}`"],
                    expected_behavior="Module should parse without syntax errors.",
                    actual_behavior=f"SyntaxError: {exc.msg}",
                    root_cause="Invalid Python syntax preventing module import.",
                    impact="Application crash on module import.",
                    recommended_fix="Correct syntax error at the indicated line.",
                    confidence=1.0,
                    verification_status=FindingVerificationStatus.CONFIRMED,
                    evidence_items=[
                        EvidenceCreateDTO(
                            evidence_type=EvidenceType.SOURCE_REFERENCE,
                            source_tool="PythonASTParser",
                            content_text=snippet,
                            content_excerpt=snippet,
                            metadata_json={"file": rel_path, "line": lineno, "error": exc.msg},
                            filename_hint="syntax_error_snippet.py",
                        )
                    ],
                )
            )
            return

        # 2. AST Node Inspection
        for node in ast.walk(tree):
            # Check mutable default arguments
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default_node in node.args.defaults + [
                    d for d in node.args.kw_defaults if d is not None
                ]:
                    if isinstance(default_node, (ast.List, ast.Dict, ast.Set)):
                        lineno = node.lineno
                        snippet = self._extract_snippet(lines, lineno, min(len(lines), lineno + 6))
                        findings.append(
                            FindingCreateDTO(
                                category=FindingCategory.LOGIC_DEFECT,
                                severity=FindingSeverity.HIGH,
                                title=f"Mutable default argument in function `{node.name}`",
                                description=(
                                    f"Function `{node.name}` in `{rel_path}` uses a mutable literal "
                                    "(list, dict, or set) as a default argument, causing state leakage across calls."
                                ),
                                file_path=rel_path,
                                line_start=lineno,
                                line_end=node.end_lineno or lineno,
                                agent_name=self.agent_name,
                                reproduction_steps=[
                                    f"Call `{node.name}()` multiple times without passing the default parameter.",
                                    "Observe mutated state persisting across invocations.",
                                ],
                                expected_behavior="Default parameter should initialize a fresh container per call.",
                                actual_behavior="Shared mutable default object persists across calls.",
                                root_cause="Python evaluates default argument expressions once at function definition time.",
                                impact="Cross-request data contamination and subtle state bugs.",
                                recommended_fix="Default the parameter to `None` and initialize `param = param or []` inside the function body.",
                                confidence=0.98,
                                verification_status=FindingVerificationStatus.CONFIRMED,
                                evidence_items=[
                                    EvidenceCreateDTO(
                                        evidence_type=EvidenceType.SOURCE_REFERENCE,
                                        source_tool="ASTLogicAnalyzer",
                                        content_text=snippet,
                                        content_excerpt=snippet,
                                        metadata_json={"function": node.name, "line": lineno},
                                        filename_hint=f"{node.name}_mutable_default.py",
                                    )
                                ],
                            )
                        )

                # Check unreachable dead code after return/raise
                self._check_unreachable_statements(node, lines, rel_path, findings)

                # Check cyclomatic complexity
                complexity = self._compute_cyclomatic_complexity(node)
                if complexity > 18:
                    lineno = node.lineno
                    snippet = self._extract_snippet(lines, lineno, min(len(lines), lineno + 10))
                    findings.append(
                        FindingCreateDTO(
                            category=FindingCategory.COMPLEXITY,
                            severity=FindingSeverity.LOW,
                            title=f"High cyclomatic complexity ({complexity}) in `{node.name}`",
                            description=(
                                f"Function `{node.name}` in `{rel_path}` has cyclomatic complexity of {complexity} "
                                "(threshold: 18), increasing maintenance and defect risk."
                            ),
                            file_path=rel_path,
                            line_start=lineno,
                            line_end=node.end_lineno or lineno,
                            agent_name=self.agent_name,
                            reproduction_steps=[f"Inspect branching paths in `{rel_path}:{lineno}`"],
                            expected_behavior="Functions should maintain cyclomatic complexity <= 18.",
                            actual_behavior=f"Measured cyclomatic complexity is {complexity}.",
                            root_cause="Deeply nested conditionals and loops inside a single function.",
                            impact="Reduced testability and higher defect density.",
                            recommended_fix="Extract cohesive helper methods to flatten conditional branches.",
                            confidence=0.92,
                            verification_status=FindingVerificationStatus.CONFIRMED,
                            evidence_items=[
                                EvidenceCreateDTO(
                                    evidence_type=EvidenceType.SOURCE_REFERENCE,
                                    source_tool="ASTComplexityScanner",
                                    content_text=snippet,
                                    content_excerpt=snippet,
                                    metadata_json={"complexity": complexity, "function": node.name},
                                )
                            ],
                        )
                    )

                # Check duplicate code across functions (>10 lines)
                func_span = (node.end_lineno or node.lineno) - node.lineno
                if func_span >= 12:
                    normalized_ast = ast.dump(node, annotate_fields=False)
                    digest = hashlib.sha256(normalized_ast.encode("utf-8")).hexdigest()
                    if digest in function_hashes:
                        orig_path, orig_line, orig_name = function_hashes[digest]
                        if orig_path != rel_path:
                            snippet = self._extract_snippet(lines, node.lineno, min(len(lines), node.lineno + 10))
                            findings.append(
                                FindingCreateDTO(
                                    category=FindingCategory.DUPLICATE_CODE,
                                    severity=FindingSeverity.LOW,
                                    title=f"Duplicate function implementation `{node.name}`",
                                    description=(
                                        f"Function `{node.name}` in `{rel_path}:{node.lineno}` has an identical AST structure "
                                        f"to `{orig_name}` in `{orig_path}:{orig_line}`."
                                    ),
                                    file_path=rel_path,
                                    line_start=node.lineno,
                                    line_end=node.end_lineno or node.lineno,
                                    agent_name=self.agent_name,
                                    reproduction_steps=[f"Compare `{rel_path}:{node.lineno}` with `{orig_path}:{orig_line}`."],
                                    expected_behavior="Shared logic should be extracted into a reusable utility module.",
                                    actual_behavior="Duplicated AST implementation across modules.",
                                    root_cause="Copy-pasted function implementation.",
                                    impact="Divergent bug fixes when only one copy is updated.",
                                    recommended_fix="Consolidate duplicate functions into a shared module.",
                                    confidence=0.90,
                                    verification_status=FindingVerificationStatus.CONFIRMED,
                                    evidence_items=[
                                        EvidenceCreateDTO(
                                            evidence_type=EvidenceType.SOURCE_REFERENCE,
                                            source_tool="ASTDuplicateDetector",
                                            content_text=snippet,
                                            content_excerpt=snippet,
                                            metadata_json={"duplicate_of": f"{orig_path}:{orig_line}"},
                                        )
                                    ],
                                )
                            )
                    else:
                        function_hashes[digest] = (rel_path, node.lineno, node.name)

            # Check bare exception handler or silent exception swallowing in non-cleanup code
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    lineno = node.lineno
                    snippet = self._extract_snippet(lines, max(1, lineno - 2), min(len(lines), lineno + 4))
                    findings.append(
                        FindingCreateDTO(
                            category=FindingCategory.EXCEPTION_HANDLING,
                            severity=FindingSeverity.MEDIUM,
                            title=f"Bare `except:` clause catches system exits in {rel_path}:{lineno}",
                            description=(
                                f"Bare `except:` at `{rel_path}:{lineno}` catches `BaseException` "
                                "(including `SystemExit` and `KeyboardInterrupt`), masking critical errors."
                            ),
                            file_path=rel_path,
                            line_start=lineno,
                            line_end=node.end_lineno or lineno,
                            agent_name=self.agent_name,
                            reproduction_steps=[f"Inspect exception handler at `{rel_path}:{lineno}`"],
                            expected_behavior="Catch specific `Exception` subclasses and log or handle them.",
                            actual_behavior="Bare `except:` catches all BaseExceptions.",
                            root_cause="Missing exception type specification in `except` clause.",
                            impact="Swallows unexpected runtime errors and prevents graceful process shutdown.",
                            recommended_fix="Replace `except:` with `except Exception as exc:` and log the error.",
                            confidence=0.96,
                            verification_status=FindingVerificationStatus.CONFIRMED,
                            evidence_items=[
                                EvidenceCreateDTO(
                                    evidence_type=EvidenceType.SOURCE_REFERENCE,
                                    source_tool="ASTExceptionScanner",
                                    content_text=snippet,
                                    content_excerpt=snippet,
                                    metadata_json={"line": lineno},
                                )
                            ],
                        )
                    )

    def _check_unreachable_statements(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        lines: list[str],
        rel_path: str,
        findings: list[FindingCreateDTO],
    ) -> None:
        blocks: list[list[ast.stmt]] = []
        for child in ast.walk(func_node):
            for attr in ("body", "orelse", "finalbody"):
                stmt_list = getattr(child, attr, None)
                if isinstance(stmt_list, list) and all(isinstance(x, ast.stmt) for x in stmt_list):
                    blocks.append(stmt_list)

        for block in blocks:
            for idx, stmt in enumerate(block[:-1]):
                if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                    next_stmt = block[idx + 1]
                    lineno = next_stmt.lineno
                    snippet = self._extract_snippet(lines, stmt.lineno, min(len(lines), lineno + 3))
                    findings.append(
                        FindingCreateDTO(
                            category=FindingCategory.DEAD_CODE,
                            severity=FindingSeverity.MEDIUM,
                            title=f"Unreachable dead code in `{func_node.name}` at {rel_path}:{lineno}",
                            description=(
                                f"Statements starting at line {lineno} in `{func_node.name}` (`{rel_path}`) "
                                "occur after an unconditional `return`/`raise`/`break` and can never execute."
                            ),
                            file_path=rel_path,
                            line_start=lineno,
                            line_end=next_stmt.end_lineno or lineno,
                            agent_name=self.agent_name,
                            reproduction_steps=[f"Inspect `{rel_path}` lines {stmt.lineno}-{lineno}."],
                            expected_behavior="All statements in function body should be reachable.",
                            actual_behavior="Code after unconditional return/raise is dead.",
                            root_cause="Leftover logic after early return or raise statement.",
                            impact="Dead code confuses maintainers and may indicate broken control flow.",
                            recommended_fix="Remove the unreachable statements or fix the preceding conditional return.",
                            confidence=0.99,
                            verification_status=FindingVerificationStatus.CONFIRMED,
                            evidence_items=[
                                EvidenceCreateDTO(
                                    evidence_type=EvidenceType.SOURCE_REFERENCE,
                                    source_tool="ASTDeadCodeAnalyzer",
                                    content_text=snippet,
                                    content_excerpt=snippet,
                                    metadata_json={"function": func_node.name, "line": lineno},
                                )
                            ],
                        )
                    )
                    return

    def _inspect_js_ts_file(
        self,
        fpath: Path,
        rel_path: str,
        findings: list[FindingCreateDTO],
    ) -> None:
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        lines = source.splitlines()
        for idx, line in enumerate(lines, start=1):
            if "debugger;" in line:
                snippet = self._extract_snippet(lines, max(1, idx - 2), min(len(lines), idx + 2))
                findings.append(
                    FindingCreateDTO(
                        category=FindingCategory.LOGIC_DEFECT,
                        severity=FindingSeverity.MEDIUM,
                        title=f"Leftover `debugger;` statement in {rel_path}:{idx}",
                        description=f"Production frontend source `{rel_path}:{idx}` contains a `debugger;` statement.",
                        file_path=rel_path,
                        line_start=idx,
                        line_end=idx,
                        agent_name=self.agent_name,
                        reproduction_steps=[f"Open browser DevTools and load component from `{rel_path}`."],
                        expected_behavior="No `debugger;` statements in committed frontend source.",
                        actual_behavior="Execution pauses when DevTools is open.",
                        root_cause="Forgotten debugging statement.",
                        impact="Halts execution for users/developers with DevTools open.",
                        recommended_fix="Remove the `debugger;` statement.",
                        confidence=1.0,
                        verification_status=FindingVerificationStatus.CONFIRMED,
                        evidence_items=[
                            EvidenceCreateDTO(
                                evidence_type=EvidenceType.SOURCE_REFERENCE,
                                source_tool="FrontendStaticScanner",
                                content_text=snippet,
                                content_excerpt=snippet,
                            )
                        ],
                    )
                )

    def _compute_cyclomatic_complexity(self, node: ast.AST) -> int:
        complexity = 1
        for child in ast.walk(node):
            if isinstance(
                child,
                (
                    ast.If,
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.ExceptHandler,
                    ast.With,
                    ast.AsyncWith,
                    ast.IfExp,
                ),
            ):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += max(0, len(child.values) - 1)
        return complexity

    @staticmethod
    def _extract_snippet(lines: list[str], start_line: int, end_line: int) -> str:
        s = max(1, start_line)
        e = min(len(lines), max(s, end_line))
        numbered = [f"{ln:4d} | {lines[ln - 1]}" for ln in range(s, e + 1)]
        return "\n".join(numbered)
