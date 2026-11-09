# Autonomous QC & Project Audit Intelligence Platform (Version 1.0)

Production-grade **Autonomous Software Quality-Control & Project Audit Intelligence Platform** operating in two unified modes sharing a single Clean Architecture audit engine, 20-entity universal database schema (PostgreSQL 18 + Zero-Config Embedded SQLite Fallback), SHA-256 evidence vault, and human-controlled remediation pipeline:

- **Mode A — Standalone QC Platform**: FastAPI v1 backend + Minimal, Theme-Switchable (Dark / Light) React/TypeScript/Vite/Tailwind/Recharts dashboard.
- **Mode B — Project-Integrated QC Agent (`qc-agent`)**: Distributable Python CLI (`qc_agent_cli/qc_agent/cli.py`) configured via `.qc/config.yaml`.

---

## Universal Portability & Zero-Config Execution

This platform is architected to run **out of the box on any laptop** without manual database setup or port conflicts:

1. **Self-Contained `QC_Intelligence_Platform.exe` (Windows)**:
   - Bundles the Python runtime, FastAPI, Uvicorn, SQLAlchemy 2.x, `aiosqlite`, `asyncpg`, and the compiled React `frontend/dist` inside a single executable.
2. **Automatic Database Fallback (PostgreSQL 18 or Embedded SQLite)**:
   - Automatically connects to PostgreSQL (`127.0.0.1:5433`) when available, or seamlessly falls back to a zero-config embedded SQLite database (`storage/qc_platform_universal.db`) if PostgreSQL is not installed on the user's laptop.
3. **Smart Port Conflict Detection & Auto-Failover**:
   - Before binding or opening the UI, the launcher verifies whether `127.0.0.1:8000` is genuinely serving the Autonomous QC Platform (`/api/v1/system/health`). If another service on a developer's laptop occupies port `8000`, the launcher automatically selects the next available port (`8001`, `8002`, etc.) so it never collides with another local server.
4. **Minimal UI/UX with Dark & Light Theme Switcher**:
   - Clean, streamlined workspace sidebar with collapsible advanced inspector views and a one-click **Light Mode / Dark Mode** theme toggle in the top header.

---

## Quick Start (Any Laptop)

### Option A — Run the Standalone Windows `.exe` (Zero Install)
Double-click **`QC_Intelligence_Platform.exe`** in the repository root (or run `start_platform.bat`):
```powershell
.\QC_Intelligence_Platform.exe
```

### Option B — Cross-Platform One-Click Launcher (`Windows` / `macOS` / `Linux`)
- **Windows**:
  ```powershell
  .\start_platform.bat
  ```
- **macOS / Linux**:
  ```bash
  chmod +x start_platform.sh
  ./start_platform.sh
  ```

### Option C — Manual Developer Startup
```powershell
# Run Automated Test Suite (Works on both PostgreSQL and Embedded SQLite)
python -m pytest backend/tests qc_agent_cli/tests -v

# Start Unified Server (FastAPI + React UI)
python desktop_launcher.py
```

### Option D — Run Mode B (`qc-agent` CLI)
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
