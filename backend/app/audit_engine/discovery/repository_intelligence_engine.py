"""Repository Intelligence Engine — Technology-independent discovery & manifest builder."""

import ast
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.constants.defaults import DEFAULT_EXCLUDED_DIRS, DEFAULT_EXCLUDED_EXTENSIONS

LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".ps1": "PowerShell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".ini": "INI",
    ".md": "Markdown",
    ".mako": "Mako",
}

PACKAGE_MANIFEST_FILES: set[str] = {
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "Pipfile",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "composer.json",
    "Gemfile",
}

ENTRYPOINT_PATTERNS: set[str] = {
    "main.py",
    "app.py",
    "wsgi.py",
    "asgi.py",
    "manage.py",
    "cli.py",
    "__main__.py",
    "server.js",
    "server.ts",
    "index.js",
    "index.ts",
    "main.ts",
    "main.tsx",
    "App.tsx",
    "App.jsx",
}

JS_IMPORT_RE = re.compile(
    r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))"""
)


class RepositoryIntelligenceEngine:
    """Discovers files, languages, frameworks, DBs, boundaries, dependencies, and generates manifest."""

    def __init__(
        self,
        custom_exclusions: list[str] | None = None,
        max_file_size_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self.excluded_dirs = set(DEFAULT_EXCLUDED_DIRS)
        self.custom_exclusions = set(custom_exclusions or [])
        self.excluded_extensions = set(DEFAULT_EXCLUDED_EXTENSIONS)
        self.max_file_size_bytes = max_file_size_bytes

    def discover_repository(self, root_path: str | Path) -> dict[str, Any]:
        root = Path(root_path).resolve()
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Repository path does not exist or is not a directory: {root}")

        file_records: list[dict[str, Any]] = []
        languages_counter: dict[str, int] = {}
        frameworks: set[str] = set()
        databases: set[str] = set()
        infrastructure: set[str] = set()
        test_frameworks: set[str] = set()
        package_manifests: list[str] = []
        entrypoints: list[dict[str, str]] = []
        migration_files: list[str] = []
        config_files: list[str] = []
        dependency_graph: dict[str, list[str]] = {}
        external_dependencies: dict[str, list[str]] = {"python": [], "node": [], "other": []}
        applications_detected: dict[str, dict[str, Any]] = {
            "backends": [],
            "frontends": [],
            "cli_packages": [],
        }

        for current_root, dirs, files in os.walk(root, topdown=True):
            rel_dir = Path(current_root).relative_to(root)
            # Record excluded directories explicitly so coverage tracking is transparent
            kept_dirs: list[str] = []
            for d in sorted(dirs):
                rel_d_str = (rel_dir / d).as_posix() if str(rel_dir) != "." else d
                if d in self.excluded_dirs or self._matches_custom_exclusion(rel_d_str):
                    file_records.append(
                        {
                            "relative_path": f"{rel_d_str}/",
                            "file_type": "directory",
                            "language": "Excluded Directory",
                            "size_bytes": 0,
                            "line_count": 0,
                            "sha256_hash": None,
                            "inspection_status": "EXCLUDED",
                            "status_reason": f"Excluded directory policy ({d})",
                            "is_entrypoint": False,
                            "is_test_file": False,
                            "component_boundary": "UNKNOWN",
                            "imports_dependencies": [],
                        }
                    )
                else:
                    kept_dirs.append(d)
            dirs[:] = kept_dirs

            for filename in sorted(files):
                abs_file = Path(current_root) / filename
                rel_path = abs_file.relative_to(root).as_posix()

                # Check infrastructure files
                self._detect_infrastructure_by_filename(filename, rel_path, infrastructure)

                try:
                    stat = abs_file.stat()
                    size_bytes = stat.st_size
                except OSError as exc:
                    file_records.append(
                        {
                            "relative_path": rel_path,
                            "file_type": "unreadable",
                            "language": "Unknown",
                            "size_bytes": 0,
                            "line_count": 0,
                            "sha256_hash": None,
                            "inspection_status": "FAILED",
                            "status_reason": f"OS stat error: {exc}",
                            "is_entrypoint": False,
                            "is_test_file": False,
                            "component_boundary": "UNKNOWN",
                            "imports_dependencies": [],
                        }
                    )
                    continue

                ext = abs_file.suffix.lower()
                if self._matches_custom_exclusion(rel_path):
                    file_records.append(
                        {
                            "relative_path": rel_path,
                            "file_type": ext or "file",
                            "language": LANGUAGE_BY_EXTENSION.get(ext, "Other"),
                            "size_bytes": size_bytes,
                            "line_count": 0,
                            "sha256_hash": None,
                            "inspection_status": "EXCLUDED",
                            "status_reason": "Matched project custom exclusion pattern",
                            "is_entrypoint": False,
                            "is_test_file": False,
                            "component_boundary": self._classify_boundary(rel_path, filename),
                            "imports_dependencies": [],
                        }
                    )
                    continue

                if ext in self.excluded_extensions:
                    file_records.append(
                        {
                            "relative_path": rel_path,
                            "file_type": ext,
                            "language": "Binary/Asset",
                            "size_bytes": size_bytes,
                            "line_count": 0,
                            "sha256_hash": self._hash_file_safe(abs_file),
                            "inspection_status": "EXCLUDED",
                            "status_reason": f"Binary or static asset extension ({ext})",
                            "is_entrypoint": False,
                            "is_test_file": False,
                            "component_boundary": self._classify_boundary(rel_path, filename),
                            "imports_dependencies": [],
                        }
                    )
                    continue

                language = self._detect_language(filename, ext)
                boundary = self._classify_boundary(rel_path, filename)
                is_test = self._is_test_file(rel_path, filename)
                is_entry = filename in ENTRYPOINT_PATTERNS and not is_test

                if filename in PACKAGE_MANIFEST_FILES or filename.endswith(".csproj"):
                    package_manifests.append(rel_path)

                if self._is_config_file(filename, ext):
                    config_files.append(rel_path)

                if self._is_migration_or_schema(rel_path, filename, ext):
                    migration_files.append(rel_path)

                # Read content safely
                sha256_hash = self._hash_file_safe(abs_file)
                inspection_status = "PENDING"
                status_reason: str | None = None
                line_count = 0
                imports: list[str] = []

                if size_bytes > self.max_file_size_bytes:
                    inspection_status = "PARTIALLY_INSPECTED"
                    status_reason = (
                        f"Large file ({size_bytes} bytes > {self.max_file_size_bytes} threshold); chunked header inspected"
                    )
                    content = self._read_text_chunk(abs_file, max_bytes=262144)
                else:
                    content, read_err = self._read_text_full(abs_file)
                    if read_err is not None:
                        inspection_status = "UNSUPPORTED" if "binary" in read_err else "FAILED"
                        status_reason = read_err

                if content is not None:
                    line_count = content.count("\n") + (1 if content else 0)
                    if language != "Other":
                        languages_counter[language] = languages_counter.get(language, 0) + 1
                    imports = self._extract_imports(language, content, rel_path)
                    if imports:
                        dependency_graph[rel_path] = imports

                    # Inspect manifests & source content for frameworks, databases, and test runners
                    self._analyze_content_signals(
                        filename=filename,
                        rel_path=rel_path,
                        content=content,
                        imports=imports,
                        frameworks=frameworks,
                        databases=databases,
                        test_frameworks=test_frameworks,
                        external_dependencies=external_dependencies,
                    )

                    if inspection_status == "PENDING":
                        inspection_status = "INSPECTED"
                        status_reason = "Source file inventoried and parsed"

                if is_entry:
                    entrypoints.append(
                        {
                            "path": rel_path,
                            "boundary": boundary,
                            "language": language,
                        }
                    )
                    if boundary == "BACKEND":
                        applications_detected["backends"].append(
                            {"entrypoint": rel_path, "language": language}
                        )
                    elif boundary == "FRONTEND":
                        applications_detected["frontends"].append(
                            {"entrypoint": rel_path, "language": language}
                        )
                    else:
                        applications_detected["cli_packages"].append(
                            {"entrypoint": rel_path, "language": language}
                        )

                file_records.append(
                    {
                        "relative_path": rel_path,
                        "file_type": ext or filename,
                        "language": language,
                        "size_bytes": size_bytes,
                        "line_count": line_count,
                        "sha256_hash": sha256_hash,
                        "inspection_status": inspection_status,
                        "status_reason": status_reason,
                        "is_entrypoint": is_entry,
                        "is_test_file": is_test,
                        "component_boundary": boundary,
                        "imports_dependencies": imports,
                        "inspected_at": datetime.now(UTC),
                    }
                )

        # Compute coverage summary metrics
        status_counts: dict[str, int] = {
            "PENDING": 0,
            "INSPECTED": 0,
            "EXCLUDED": 0,
            "UNSUPPORTED": 0,
            "FAILED": 0,
            "PARTIALLY_INSPECTED": 0,
        }
        for rec in file_records:
            st = rec["inspection_status"]
            status_counts[st] = status_counts.get(st, 0) + 1

        total_discovered = len(file_records)
        excluded_count = status_counts["EXCLUDED"]
        in_scope_count = max(0, total_discovered - excluded_count)
        inspected_count = status_counts["INSPECTED"] + status_counts["PARTIALLY_INSPECTED"]
        coverage_pct = (
            round((inspected_count / in_scope_count) * 100.0, 2) if in_scope_count > 0 else 100.0
        )

        git_info = self._extract_git_metadata(root)
        audit_plan = self._generate_audit_plan(
            languages=list(languages_counter.keys()),
            frameworks=sorted(frameworks),
            databases=sorted(databases),
            applications=applications_detected,
            test_frameworks=sorted(test_frameworks),
        )

        manifest: dict[str, Any] = {
            "project_name": root.name,
            "root_path": str(root),
            "discovered_at": datetime.now(UTC).isoformat(),
            "git": git_info,
            "languages": sorted(languages_counter.keys(), key=lambda k: -languages_counter[k]),
            "language_file_counts": languages_counter,
            "frameworks": sorted(frameworks),
            "databases": sorted(databases),
            "infrastructure": sorted(infrastructure),
            "test_frameworks": sorted(test_frameworks),
            "package_manifests": package_manifests,
            "entrypoints": entrypoints,
            "applications": applications_detected,
            "backend": {
                "detected": len(applications_detected["backends"]) > 0
                or any(r["component_boundary"] == "BACKEND" for r in file_records if r["inspection_status"] == "INSPECTED"),
                "entrypoints": [e["entrypoint"] for e in applications_detected["backends"]],
            },
            "frontend": {
                "detected": len(applications_detected["frontends"]) > 0
                or any(r["component_boundary"] == "FRONTEND" for r in file_records if r["inspection_status"] == "INSPECTED"),
                "entrypoints": [e["entrypoint"] for e in applications_detected["frontends"]],
            },
            "config_files": config_files,
            "migration_and_schema_files": migration_files,
            "external_dependencies": {
                k: sorted(set(v)) for k, v in external_dependencies.items()
            },
            "dependency_graph_edges": sum(len(v) for v in dependency_graph.values()),
            "dependency_graph": dependency_graph,
            "coverage": {
                "files_discovered": total_discovered,
                "files_in_scope": in_scope_count,
                "files_inspected": status_counts["INSPECTED"],
                "files_partially_inspected": status_counts["PARTIALLY_INSPECTED"],
                "files_excluded": excluded_count,
                "files_unsupported": status_counts["UNSUPPORTED"],
                "files_failed": status_counts["FAILED"],
                "files_pending": status_counts["PENDING"],
                "inspection_coverage_percent": coverage_pct,
            },
            "audit_plan": audit_plan,
            "discovery_complete": True,
        }

        return {
            "manifest": manifest,
            "files": file_records,
        }

    def _matches_custom_exclusion(self, rel_path: str) -> bool:
        for pattern in self.custom_exclusions:
            clean = pattern.strip("/")
            if clean and (rel_path == clean or rel_path.startswith(f"{clean}/") or clean in rel_path):
                return True
        return False

    def _detect_language(self, filename: str, ext: str) -> str:
        if filename.lower().startswith("dockerfile"):
            return "Dockerfile"
        return LANGUAGE_BY_EXTENSION.get(ext, "Other")

    def _detect_infrastructure_by_filename(
        self, filename: str, rel_path: str, infrastructure: set[str]
    ) -> None:
        lower = filename.lower()
        if lower.startswith("dockerfile"):
            infrastructure.add("Docker")
        if "docker-compose" in lower or "compose.y" in lower:
            infrastructure.add("Docker Compose")
        if ".github/workflows" in rel_path.lower():
            infrastructure.add("GitHub Actions")
        if "k8s" in rel_path.lower() or "kubernetes" in rel_path.lower():
            infrastructure.add("Kubernetes")

    def _classify_boundary(self, rel_path: str, filename: str) -> str:
        lower = rel_path.lower()
        if any(p in lower for p in ("test/", "tests/", "__tests__", ".spec.", ".test.", "test_")):
            return "TESTS"
        if any(p in lower for p in ("alembic/", "migrations/", "schema.sql", "prisma/")):
            return "DATABASE"
        if any(p in lower for p in ("frontend/", "client/", "web/", "src/pages", "src/components", ".tsx", ".jsx")):
            return "FRONTEND"
        if any(p in lower for p in ("backend/", "server/", "api/", "app/models", "app/agents", "app/audit_engine")):
            return "BACKEND"
        if any(p in lower for p in ("infrastructure/", "docker", ".github/", "deployment/")):
            return "INFRASTRUCTURE"
        if any(p in lower for p in ("shared/", "common/", "contracts/")):
            return "SHARED"
        if any(p in lower for p in ("docs/", "readme")):
            return "DOCS"
        if filename.startswith(".") or filename.endswith((".yaml", ".yml", ".toml", ".ini", ".json")):
            return "CONFIG"
        return "BACKEND" if filename.endswith(".py") else "UNKNOWN"

    def _is_test_file(self, rel_path: str, filename: str) -> bool:
        lower = rel_path.lower()
        return (
            filename.startswith("test_")
            or filename.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".test.js"))
            or "/tests/" in f"/{lower}"
        )

    def _is_config_file(self, filename: str, ext: str) -> bool:
        return ext in {".yaml", ".yml", ".toml", ".ini"} or filename in {
            ".env.example",
            "tsconfig.json",
            "vite.config.ts",
            "tailwind.config.js",
            "alembic.ini",
        }

    def _is_migration_or_schema(self, rel_path: str, filename: str, ext: str) -> bool:
        lower = rel_path.lower()
        return (
            ext == ".sql"
            or "alembic/versions" in lower
            or "migrations/" in lower
            or filename in {"entities.py", "models.py", "schema.prisma"}
        )

    def _hash_file_safe(self, path: Path) -> str | None:
        try:
            h = hashlib.sha256()
            with path.open("rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None

    def _read_text_full(self, path: Path) -> tuple[str | None, str | None]:
        try:
            raw = path.read_bytes()
            if b"\x00" in raw[:4096]:
                return None, "Detected binary content (null byte)"
            return raw.decode("utf-8", errors="replace"), None
        except OSError as exc:
            return None, f"Read error: {exc}"

    def _read_text_chunk(self, path: Path, max_bytes: int = 262144) -> str | None:
        try:
            with path.open("rb") as f:
                raw = f.read(max_bytes)
            return raw.decode("utf-8", errors="replace")
        except OSError:
            return None

    def _extract_imports(self, language: str, content: str, _rel_path: str) -> list[str]:
        imports: set[str] = set()
        if language == "Python":
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.add(alias.name)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.add(node.module)
            except SyntaxError:
                pass
        elif language in {"JavaScript", "TypeScript"}:
            for match in JS_IMPORT_RE.finditer(content):
                mod = match.group(1) or match.group(2)
                if mod:
                    imports.add(mod)
        return sorted(imports)

    def _analyze_content_signals(
        self,
        filename: str,
        rel_path: str,
        content: str,
        imports: list[str],
        frameworks: set[str],
        databases: set[str],
        test_frameworks: set[str],
        external_dependencies: dict[str, list[str]],
    ) -> None:
        lower = content.lower()
        import_roots = {imp.split(".")[0].lower() for imp in imports}
        is_manifest_or_cfg = filename in {
            "requirements.txt",
            "pyproject.toml",
            "Pipfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            ".env",
            ".env.example",
            "config.py",
            "alembic.ini",
        }

        if filename == "requirements.txt":
            for line in content.splitlines():
                clean = line.strip()
                if clean and not clean.startswith("#"):
                    pkg = re.split(r"[><=~!\[]", clean)[0].strip()
                    if pkg:
                        external_dependencies["python"].append(pkg)

        if filename == "package.json":
            try:
                data = json.loads(content)
                deps = {
                    **data.get("dependencies", {}),
                    **data.get("devDependencies", {}),
                }
                for dep_name in deps:
                    external_dependencies["node"].append(dep_name)
                if "react" in deps:
                    frameworks.add("React")
                if "next" in deps:
                    frameworks.add("Next.js")
                if "vue" in deps:
                    frameworks.add("Vue")
                if "@angular/core" in deps:
                    frameworks.add("Angular")
                if "express" in deps:
                    frameworks.add("Express")
                if "@nestjs/core" in deps:
                    frameworks.add("NestJS")
                if "vite" in deps:
                    frameworks.add("Vite")
                if "tailwindcss" in deps:
                    frameworks.add("Tailwind CSS")
                if "@playwright/test" in deps or "playwright" in deps:
                    test_frameworks.add("playwright")
                if "vitest" in deps:
                    test_frameworks.add("vitest")
                if "jest" in deps:
                    test_frameworks.add("jest")
            except Exception:
                pass

        if "fastapi" in import_roots or (is_manifest_or_cfg and "fastapi" in lower):
            frameworks.add("FastAPI")
        if "flask" in import_roots or (is_manifest_or_cfg and "flask" in lower):
            frameworks.add("Flask")
        if "django" in import_roots or (is_manifest_or_cfg and "django" in lower):
            frameworks.add("Django")
        if "sqlalchemy" in import_roots or (is_manifest_or_cfg and "sqlalchemy" in lower):
            frameworks.add("SQLAlchemy 2.x")
        if "alembic" in import_roots or (is_manifest_or_cfg and "alembic" in lower):
            frameworks.add("Alembic")
        if "pydantic" in import_roots or "pydantic_settings" in import_roots or (
            is_manifest_or_cfg and "pydantic" in lower
        ):
            frameworks.add("Pydantic V2")

        if (
            any(k in import_roots for k in ("asyncpg", "psycopg2", "psycopg"))
            or (is_manifest_or_cfg and any(k in lower for k in ("postgresql", "asyncpg", "psycopg2")))
        ):
            databases.add("PostgreSQL")
        if (
            any(k in import_roots for k in ("pymysql", "aiomysql", "mysqldb"))
            or (is_manifest_or_cfg and any(k in lower for k in ("mysql://", "pymysql", "aiomysql")))
        ):
            databases.add("MySQL")
        if "sqlite3" in import_roots or "aiosqlite" in import_roots or (
            is_manifest_or_cfg and "sqlite" in lower
        ):
            databases.add("SQLite")
        if (
            any(k in import_roots for k in ("pymongo", "motor"))
            or (is_manifest_or_cfg and any(k in lower for k in ("mongodb://", "pymongo", "motor")))
        ):
            databases.add("MongoDB")
        if "redis" in import_roots or (is_manifest_or_cfg and "redis" in lower):
            databases.add("Redis")
        if "supabase" in import_roots or (is_manifest_or_cfg and "supabase" in lower):
            databases.add("Supabase")

        if "pytest" in import_roots or (is_manifest_or_cfg and "pytest" in lower):
            test_frameworks.add("pytest")
        if "playwright" in import_roots or (is_manifest_or_cfg and "playwright" in lower):
            test_frameworks.add("playwright")
        if "httpx" in import_roots and "test" in rel_path.lower():
            test_frameworks.add("httpx")

    def _extract_git_metadata(self, root: Path) -> dict[str, Any]:
        commit_hash = None
        branch_name = None
        is_dirty = False
        try:
            res_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if res_commit.returncode == 0:
                commit_hash = res_commit.stdout.strip()
            res_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if res_branch.returncode == 0:
                branch_name = res_branch.stdout.strip()
            res_status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if res_status.returncode == 0:
                is_dirty = bool(res_status.stdout.strip())
        except Exception:
            pass
        return {
            "commit_hash": commit_hash or "uncommitted-snapshot",
            "branch": branch_name or "main",
            "is_dirty": is_dirty,
        }

    def _generate_audit_plan(
        self,
        languages: list[str],
        frameworks: list[str],
        databases: list[str],
        applications: dict[str, Any],
        test_frameworks: list[str],
    ) -> list[dict[str, Any]]:
        """Generate a deterministic DAG of audit tasks tailored to the discovered stack."""
        tasks: list[dict[str, Any]] = [
            {
                "task_key": "repository_intelligence",
                "agent_type": "RepositoryIntelligenceAgent",
                "phase": "DISCOVERY",
                "dependencies": [],
                "reason": "Inventory all repository files, boundaries, and technology stack",
            },
            {
                "task_key": "code_quality_audit",
                "agent_type": "CodeQualityAgent",
                "phase": "STATIC_ANALYSIS",
                "dependencies": ["repository_intelligence"],
                "reason": f"Analyze source files across detected languages: {', '.join(languages[:5]) or 'all'}",
            },
            {
                "task_key": "architecture_audit",
                "agent_type": "ArchitectureAuditor",
                "phase": "STATIC_ANALYSIS",
                "dependencies": ["repository_intelligence"],
                "reason": "Evaluate modularity, separation of concerns, SOLID principles, and circular dependencies",
            },
            {
                "task_key": "security_audit",
                "agent_type": "SecurityAuditor",
                "phase": "SECURITY_ANALYSIS",
                "dependencies": ["repository_intelligence"],
                "reason": "Scan for secrets, injection vectors, auth flaws, CORS/CSRF risks, and vulnerable dependencies",
            },
        ]

        if applications.get("backends") or any(f in frameworks for f in ("FastAPI", "Flask", "Django", "Express", "NestJS")):
            tasks.append(
                {
                    "task_key": "backend_qa_audit",
                    "agent_type": "BackendQAAgent",
                    "phase": "RUNTIME_QA",
                    "dependencies": ["code_quality_audit"],
                    "reason": "Validate backend initialization, API routes, request validation, auth, and error handling",
                }
            )

        if applications.get("frontends") or any(f in frameworks for f in ("React", "Next.js", "Vue", "Angular", "Vite")):
            tasks.append(
                {
                    "task_key": "frontend_qa_audit",
                    "agent_type": "FrontendQAAgent",
                    "phase": "RUNTIME_QA",
                    "dependencies": ["code_quality_audit"],
                    "reason": "Inspect browser rendering, routes, UI components, console errors, and network requests via Playwright",
                }
            )

        if databases:
            tasks.append(
                {
                    "task_key": "database_audit",
                    "agent_type": "DatabaseAuditor",
                    "phase": "DATABASE_QA",
                    "dependencies": ["repository_intelligence"],
                    "reason": f"Verify schema, migrations, constraints, relationships, and CRUD persistence ({', '.join(databases)})",
                }
            )

        tasks.append(
            {
                "task_key": "performance_audit",
                "agent_type": "PerformanceAuditor",
                "phase": "PERFORMANCE_QA",
                "dependencies": ["code_quality_audit"],
                "reason": "Measure API latency percentiles, throughput, error rates, and resource consumption",
            }
        )

        integration_deps = [
            t["task_key"]
            for t in tasks
            if t["task_key"] in {"backend_qa_audit", "frontend_qa_audit", "database_audit"}
        ] or ["code_quality_audit"]

        tasks.append(
            {
                "task_key": "integration_e2e_audit",
                "agent_type": "IntegrationAuditor",
                "phase": "INTEGRATION_QA",
                "dependencies": integration_deps,
                "reason": f"Verify end-to-end business workflows and test suites ({', '.join(test_frameworks) or 'runtime'})",
            }
        )

        return tasks
