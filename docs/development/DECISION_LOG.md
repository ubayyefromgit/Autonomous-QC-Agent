# Technical Decision Log (ADR)

## ADR-001: Modular Monorepo & Shared Core Engine for Mode A (Dashboard) and Mode B (`qc-agent` CLI)
- **Date**: 2026-11-09
- **Status**: Accepted
- **Context**: The specification requires both a centralized Standalone QC Platform (Mode A) and a Project-Integrated CLI (`qc-agent`, Mode B) using the same core audit engine, finding schemas, execution abstractions, evidence collection, and reporting system.
- **Decision**: Organize the workspace as a modular monorepo with `backend/app/audit_engine`, `backend/app/agents`, `backend/app/tools`, and `shared/` imported directly by both the FastAPI application (`backend/app`) and the CLI package (`qc_agent_cli/qc_agent`), with optional HTTP client synchronization when `qc-agent` connects to a central platform URL.

## ADR-002: Dedicated Local PostgreSQL 18 Cluster on Port 5433 for Zero-Dependency Reproducibility
- **Date**: 2026-11-09
- **Status**: Accepted
- **Context**: The host machine has PostgreSQL 18 binaries installed (`C:\Program Files\PostgreSQL\18\bin\initdb.exe`, `pg_ctl.exe`, `psql.exe`). The system requires real PostgreSQL with SQLAlchemy 2.x, JSONB, UUID primary keys, Alembic migrations, and disposable test databases for audited projects.
- **Decision**: Initialize and manage a dedicated PostgreSQL 18 cluster in `.postgres_data` running on port `5433` with trust/password authentication for `qc_user` and database `qc_platform` (configurable via `DATABASE_URL` in `.env`). This guarantees genuine PostgreSQL 18 execution, Alembic migrations, and allows `DatabaseAuditor` / `ProjectRunner` to create and drop isolated test databases (`qc_sandbox_<id>`) safely.

## ADR-003: Separation of Deterministic Execution from AI Reasoning
- **Date**: 2026-11-09
- **Status**: Accepted
- **Context**: AI must never fabricate test results or decide whether a test passed based on static reasoning.
- **Decision**: All pass/fail verification is performed by deterministic executors (`LocalProjectRunner`, `DockerProjectRunner`, AST/Ruff/Mypy/Bandit/Semgrep scanners, HTTPX API probes, Playwright browser runners, SQLAlchemy schema inspectors). The `LLMProvider` gateway (`Gemini`, `OpenAI`, `Ollama`) is invoked only after deterministic data collection to perform contextual root-cause analysis, architectural critique, and patch synthesis using externalized prompt templates (`backend/app/prompts/*.yaml`).

## ADR-004: SHA-256 Checksum-Bound Human Approval & Optimistic Concurrency for Remediation
- **Date**: 2026-11-09
- **Status**: Accepted
- **Context**: An agent must never modify original project source files without explicit human approval, nor apply a modified patch after an earlier version was approved.
- **Decision**: Every `Patch` computes `sha256_checksum = sha256(target_file_path + "\n" + unified_diff)`. `Approval` records store `approved_patch_checksum` and `RemediationProposal` uses `version_id` for optimistic concurrency. Before `apply` executes, the service verifies `approval.approved_patch_checksum == patch.sha256_checksum` and verifies the target file's base snapshot hash, then applies the patch inside an isolated Git branch (`qc-remediation/<proposal_id>`) or isolated working copy and triggers a `RegressionRun`.

