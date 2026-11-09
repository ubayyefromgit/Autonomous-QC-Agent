# Autonomous QC & Project Audit Intelligence Platform (Version 1.0)

Production-grade **Autonomous Software Quality-Control & Project Audit Intelligence Platform** operating in two unified modes sharing a single Clean Architecture audit engine, 20-entity PostgreSQL 18 schema, SHA-256 evidence vault, and human-controlled remediation pipeline:

- **Mode A — Standalone QC Platform**: FastAPI v1 backend + 17-view React/TypeScript/Vite/Tailwind/Recharts dashboard.
- **Mode B — Project-Integrated QC Agent (`qc-agent`)**: Distributable Python CLI (`qc_agent_cli/qc_agent/cli.py`) configured via `.qc/config.yaml`.

---

## Non-Negotiable Engineering Principles

1. **Evidence First**: Every `CONFIRMED` or `REPRODUCED` finding requires immutable `Evidence` artifacts with SHA-256 checksums and automatic secret redaction.
2. **Complete File Inspection Tracking**: Every file in a repository is inventoried in `repository_files` with an explicit status (`PENDING`, `INSPECTED`, `EXCLUDED`, `UNSUPPORTED`, `FAILED`, `PARTIALLY_INSPECTED`) and reason.
3. **Deterministic Execution**: Pass/fail verdicts come strictly from actual tool/test execution (`pytest`, `httpx`, `playwright`, `ruff`, `bandit`, Python `ast`, SQLAlchemy inspector), never from LLM guesswork.
4. **Human-Controlled Remediation**: Every proposed patch has a SHA-256 `patch_checksum`. Human approval is cryptographically bound to that checksum, applied in an isolated working branch (`qc-remediation/<id>`), and verified via automated regression testing before resolving a finding.

---

## Quick Start

### Option A — Launch Standalone Windows `.exe` Application (Recommended)
Double-click **`QC_Intelligence_Platform.exe`** in the project root (or `dist\QC_Intelligence_Platform.exe`), or run:
```powershell
.\QC_Intelligence_Platform.exe
```
When opened, `QC_Intelligence_Platform.exe`:
1. Automatically starts the local PostgreSQL 18 cluster (`127.0.0.1:5433`).
2. Starts the unified FastAPI + React UI server (`http://127.0.0.1:8000`).
3. Opens the **Interactive Launch, Project Upload, API Key & Setup Instructions UI** in a dedicated desktop window where you can:
   - View **Complete Audit & Setup Instructions** and a live **System Tools Prerequisite Table** (`python`, `git`, `pytest`, `ruff`, `bandit`, `mypy`, `node`, `npm`, `playwright`, `docker`) with exact manual install commands if any tool is missing.
   - Configure **API Keys & AI Modes** (Deterministic + Local Ollama requires **no paid API key**; optional `GEMINI_API_KEY`, `OPENAI_API_KEY`, and `GITHUB_TOKEN` can be saved directly in the UI).
   - Provide target project data via **`.zip` Archive Upload**, **Multi-File Upload**, **Native Windows Folder Browser**, or **Git Repository URL Clone**.
   - Inspect **Project-Specific Readiness & Manual Setup Instructions** (detecting missing `.env` keys from `.env.example`, Python/Node dependency commands, and providing an inline `.env` editor).

### Option B — Manual Developer Startup
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ensure_postgres.ps1
cd backend
alembic upgrade head
```

### 2. Run Automated Test Suite (Unit + Integration + CLI)
```powershell
python -m pytest backend/tests qc_agent_cli/tests -v
```

### 3. Start Mode A (Backend API + Frontend Dashboard)
```powershell
# Terminal 1: FastAPI Backend (http://127.0.0.1:8000)
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# Terminal 2: React/TypeScript Dashboard (http://127.0.0.1:5173)
cd frontend
npm run dev
```

### 4. Run Mode B (`qc-agent` CLI)
```powershell
python -m qc_agent_cli.qc_agent.cli init
python -m qc_agent_cli.qc_agent.cli config validate
python -m qc_agent_cli.qc_agent.cli discover
python -m qc_agent_cli.qc_agent.cli audit --full
python -m qc_agent_cli.qc_agent.cli findings
python -m qc_agent_cli.qc_agent.cli report --format html
python -m qc_agent_cli.qc_agent.cli report --format pdf
python -m qc_agent_cli.qc_agent.cli status
```

---

## Architecture & Documentation

- [System Architecture & Phase 0 Blueprint](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [Engineering Decision Log](docs/development/DECISION_LOG.md)
- [Implementation Progress & Verification Log](docs/development/PROGRESS.md)

