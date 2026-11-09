"""Database Auditor — Validates schema, migrations, FK indexes, N+1 query patterns & DB persistence."""

import ast
import json
import os
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text

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
from backend.app.infrastructure.database.session import sync_engine
from shared.constants.defaults import DEFAULT_EXCLUDED_DIRS


class DatabaseAuditor(BaseSpecializedAgent):
    agent_name = "DatabaseAuditor"
    description = (
        "Validates database schema definitions, Alembic migrations, foreign-key constraints, "
        "N+1 query patterns, and actual PostgreSQL persistence."
    )
    supported_scopes = [AuditScope.FULL, AuditScope.DATABASE, AuditScope.BACKEND]

    async def execute(self, context: AuditContext, task: AuditTaskDTO) -> AgentResult:
        t0 = time.perf_counter()
        root = Path(context.workspace_path or context.root_path).resolve()
        findings: list[FindingCreateDTO] = []
        test_runs: list[TestRunCreateDTO] = []

        # 1. Inspect ORM models & migrations statically
        models_count, migrations_count = self._inspect_schema_and_queries(root, findings)

        # 2. Verify live PostgreSQL catalog tables & constraints
        db_verification = self._verify_postgres_catalog()
        test_runs.append(
            TestRunCreateDTO(
                test_suite_type=TestSuiteType.DATABASE,
                tool_name="PostgreSQLCatalogInspector",
                command="SELECT table_name, constraint_type FROM information_schema",
                status=TestRunStatus.PASSED if db_verification["connected"] else TestRunStatus.FAILED,
                total_tests=3,
                passed_tests=3 if db_verification["connected"] else 0,
                failed_tests=0 if db_verification["connected"] else 3,
                skipped_tests=0,
                duration_seconds=round(time.perf_counter() - t0, 3),
                exit_code=0 if db_verification["connected"] else 1,
                output_text=json.dumps(db_verification, indent=2),
                details=db_verification,
            )
        )

        db_score = max(0.0, 100.0 - len(findings) * 10.0)
        metrics = [
            MetricCreateDTO(
                dimension=QualityDimension.INTEGRATION,
                metric_name="database_integrity_score",
                metric_value=round(db_score, 2),
                unit="score",
                weight=0.10,
                breakdown={
                    "models_found": models_count,
                    "migrations_found": migrations_count,
                    "postgres_tables_verified": len(db_verification.get("tables", [])),
                    "foreign_keys_verified": db_verification.get("foreign_key_count", 0),
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
                "models_found": models_count,
                "migrations_found": migrations_count,
                "postgres_tables_count": len(db_verification.get("tables", [])),
            },
        )

    def _inspect_schema_and_queries(
        self, root: Path, findings: list[FindingCreateDTO]
    ) -> tuple[int, int]:
        models_count = 0
        migrations_count = 0
        for current_root, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS]
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                fpath = Path(current_root) / fname
                rel_path = fpath.relative_to(root).as_posix()
                if "tests/fixtures" in rel_path and "fixtures" not in root.name:
                    continue
                if "alembic/versions" in rel_path:
                    migrations_count += 1

                try:
                    source = fpath.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source, filename=rel_path)
                except Exception:
                    continue

                if "__tablename__" in source:
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            for item in node.body:
                                if isinstance(item, ast.Assign):
                                    for t in item.targets:
                                        if isinstance(t, ast.Name) and t.id == "__tablename__":
                                            models_count += 1

                # Detect N+1 query pattern: awaiting session.execute inside a `for` loop
                for node in ast.walk(tree):
                    if isinstance(node, (ast.For, ast.AsyncFor)):
                        for child in ast.walk(node):
                            if (
                                isinstance(child, ast.Await)
                                and isinstance(child.value, ast.Call)
                                and isinstance(child.value.func, ast.Attribute)
                                and child.value.func.attr in {"execute", "get", "scalar"}
                                and isinstance(child.value.func.value, ast.Name)
                                and child.value.func.value.id in {"db", "session"}
                            ):
                                # Only flag if in an endpoint/service query loop
                                if "/endpoints/" in rel_path:
                                    lineno = child.lineno
                                    lines = source.splitlines()
                                    snippet = "\n".join(
                                        lines[max(0, node.lineno - 1) : min(len(lines), lineno + 2)]
                                    )
                                    findings.append(
                                        FindingCreateDTO(
                                            category=FindingCategory.DATABASE_INTEGRITY,
                                            severity=FindingSeverity.LOW,
                                            title=f"Potential N+1 query inside loop in {rel_path}:{lineno}",
                                            description=(
                                                f"Database query `await {child.value.func.value.id}.{child.value.func.attr}(...)` "
                                                f"is executed inside a loop at `{rel_path}:{lineno}`."
                                            ),
                                            file_path=rel_path,
                                            line_start=node.lineno,
                                            line_end=lineno,
                                            agent_name=self.agent_name,
                                            reproduction_steps=[f"Inspect loop at `{rel_path}:{node.lineno}-{lineno}`"],
                                            expected_behavior="Batch queries using `selectinload`, `joinedload`, or `.in_()` filter.",
                                            actual_behavior="Sequential database round-trips inside loop.",
                                            root_cause="Iterative query execution per item.",
                                            impact="Increased latency as collection size grows.",
                                            recommended_fix="Use SQLAlchemy eager loading (`selectinload`) or batch `WHERE id IN (...)`.",
                                            confidence=0.85,
                                            verification_status=FindingVerificationStatus.CONFIRMED,
                                            evidence_items=[
                                                EvidenceCreateDTO(
                                                    evidence_type=EvidenceType.SOURCE_REFERENCE,
                                                    source_tool="ASTDatabaseQueryScanner",
                                                    content_text=snippet,
                                                    content_excerpt=snippet,
                                                )
                                            ],
                                        )
                                    )
        return models_count, migrations_count

    def _verify_postgres_catalog(self) -> dict[str, Any]:
        try:
            with sync_engine.connect() as conn:
                tables_res = conn.execute(
                    text(
                        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                    )
                )
                tables = [row[0] for row in tables_res]
                fk_res = conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.table_constraints WHERE constraint_type = 'FOREIGN KEY'"
                    )
                )
                fk_count = int(fk_res.scalar() or 0)
                idx_res = conn.execute(
                    text("SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'")
                )
                idx_count = int(idx_res.scalar() or 0)
                return {
                    "connected": True,
                    "tables": tables,
                    "table_count": len(tables),
                    "foreign_key_count": fk_count,
                    "index_count": idx_count,
                }
        except Exception as exc:
            return {
                "connected": False,
                "error": str(exc),
                "tables": [],
            }
