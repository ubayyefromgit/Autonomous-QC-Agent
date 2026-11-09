#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "============================================================================"
echo "  AUTONOMOUS QC & PROJECT AUDIT INTELLIGENCE PLATFORM (Universal Launcher)"
echo "============================================================================"

if [ ! -d ".venv" ]; then
    echo "[1/2] Creating local Python virtual environment (.venv)..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r backend/requirements.txt
fi

echo "[2/2] Starting QC Intelligence Platform..."
.venv/bin/python desktop_launcher.py "$@"

