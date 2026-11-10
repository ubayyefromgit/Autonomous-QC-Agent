"""Universal Standalone Windows Executable (.exe) & Cross-Platform Launcher
for the Autonomous QC & Project Audit Intelligence Platform.

Key Universal Portability Guarantees:
1. Zero-Config Database Fallback: Automatically uses PostgreSQL if active, or
   seamlessly falls back to an embedded SQLite database (`aiosqlite`) on any laptop.
2. Smart Port Verification & Auto-Failover: Verifies whether port 8000 is actually
   serving the QC Intelligence Platform (`/api/v1/system/health`). If another app
   on the user's laptop occupies port 8000 (which previously caused `{"detail":"Not Found"}`),
   automatically selects the next free port (8001, 8002, ...).
3. In-Process & Bundled Execution: Runs FastAPI + Uvicorn + Bundled React UI directly
   in-process (no external Python installation required when bundled) and verifies
   HTTP 200 HTML readiness before opening the desktop window.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def _get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "backend").exists() and (exe_dir / "frontend").exists():
            return exe_dir
        if (exe_dir.parent / "backend").exists() and (exe_dir.parent / "frontend").exists():
            return exe_dir.parent
        return exe_dir
    return Path(__file__).resolve().parent


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def _is_qc_server_running(host: str, port: int) -> bool:
    """Verify that the service on host:port is genuinely the Autonomous QC Platform."""
    if not _is_port_open(host, port):
        return False
    try:
        req = urllib.request.Request(
            f"http://{host}:{port}/api/v1/system/health",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            platform_name = str(data.get("app_name") or data.get("platform") or "")
            return "Autonomous QC" in platform_name or data.get("status") == "HEALTHY"
    except Exception:
        return False


def _select_available_port(host: str, preferred_port: int) -> tuple[int, bool]:
    """Return (port, already_running_qc_server).
    If preferred_port is occupied by a DIFFERENT service, automatically pick the next free port.
    """
    if _is_qc_server_running(host, preferred_port):
        return preferred_port, True
    if not _is_port_open(host, preferred_port):
        return preferred_port, False

    print(
        f"[QC Launcher] Notice: Port {preferred_port} is occupied by another application on this machine."
    )
    for candidate in range(preferred_port + 1, preferred_port + 50):
        if _is_qc_server_running(host, candidate):
            return candidate, True
        if not _is_port_open(host, candidate):
            print(f"[QC Launcher] Auto-selected clean port: {candidate}")
            return candidate, False
    return preferred_port, False


def _ensure_postgres_or_sqlite(app_root: Path) -> None:
    if _is_port_open("127.0.0.1", 5432) or _is_port_open("127.0.0.1", 5433):
        active_port = 5432 if _is_port_open("127.0.0.1", 5432) else 5433
        print(f"[QC Launcher] Database Mode: Host PostgreSQL active on 127.0.0.1:{active_port}.")
        return

    # Check for installed PostgreSQL versions on Windows
    for pg_ver in ["18", "17", "16", "15", "14"]:
        pg_exe = Path(rf"C:\Program Files\PostgreSQL\{pg_ver}\bin\postgres.exe")
        pg_data = app_root / ".postgres_data"
        if pg_exe.exists() and pg_data.exists():
            print(f"[QC Launcher] Starting local PostgreSQL {pg_ver} cluster on port 5433...")
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [str(pg_exe), "-D", str(pg_data), "-p", "5433"],
                cwd=str(app_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            for _ in range(20):
                if _is_port_open("127.0.0.1", 5433):
                    print(f"[QC Launcher] PostgreSQL {pg_ver} started and accepting connections.")
                    return
                time.sleep(0.35)
            break

    print(
        "[QC Launcher] Database Mode: Universal Zero-Config Embedded SQLite (no external DB installation needed)."
    )


def _open_desktop_ui_window(url: str) -> None:
    """Open the interactive UI in a dedicated Edge/Chrome app window or default browser."""
    edge_candidates = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    chrome_candidates = [
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]

    for browser_bin in [*edge_candidates, *chrome_candidates]:
        if browser_bin and Path(browser_bin).exists():
            try:
                subprocess.Popen(
                    [
                        str(browser_bin),
                        f"--app={url}",
                        "--window-size=1440,920",
                    ]
                )
                return
            except Exception:
                pass

    webbrowser.open(url)


def _http_status(url: str, accept: str = "text/html") -> int:
    req = urllib.request.Request(url, headers={"Accept": accept})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return int(resp.status)


def _start_uvicorn_in_thread(port: int) -> threading.Thread:
    """Run FastAPI + Uvicorn in a background daemon thread."""
    import uvicorn

    from backend.app.main import app as fastapi_app

    config = uvicorn.Config(
        app=fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return t


def main() -> int:
    parser = argparse.ArgumentParser(description="QC Intelligence Platform Universal Desktop Launcher")
    parser.add_argument(
        "--port", type=int, default=8000, help="Preferred local port for the QC Platform UI & API"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Start server without opening UI window"
    )
    parser.add_argument(
        "--verify-startup",
        action="store_true",
        help="Start services, verify HTTP 200 health & UI readiness, and exit 0",
    )
    args = parser.parse_args()

    app_root = _get_app_root()
    os.chdir(app_root)
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    print("=" * 76)
    print("  AUTONOMOUS QC & PROJECT AUDIT INTELLIGENCE PLATFORM v1.0")
    print("  Universal Zero-Config Desktop Application (Light / Dark Minimal UI)")
    print("=" * 76)
    print(f"[QC Launcher] Application Directory: {app_root}")

    _ensure_postgres_or_sqlite(app_root)

    port, already_running = _select_available_port("127.0.0.1", args.port)
    url = f"http://127.0.0.1:{port}"

    if args.verify_startup:
        if not already_running:
            _start_uvicorn_in_thread(port)
            for _ in range(50):
                if _is_qc_server_running("127.0.0.1", port):
                    break
                time.sleep(0.25)

        st_health = _http_status(f"{url}/api/v1/system/health", accept="application/json")
        st_runtime = _http_status(f"{url}/api/v1/system/runtime-config", accept="application/json")
        st_ui = _http_status(url, accept="text/html")
        print(
            f"[QC Launcher] Verified Universal Startup on {url}! Health={st_health}, RuntimeConfig={st_runtime}, UI={st_ui}"
        )
        return 0 if (st_health == 200 and st_runtime == 200 and st_ui == 200) else 1

    if already_running:
        print(f"[QC Launcher] QC Server is already running at {url}")
        if not args.no_browser:
            print(f"[QC Launcher] Opening Interactive UI Window -> {url}")
            _open_desktop_ui_window(url)
        return 0

    if not args.no_browser:
        def _delayed_open() -> None:
            for _ in range(60):
                if _is_qc_server_running("127.0.0.1", port):
                    try:
                        if _http_status(url, accept="text/html") == 200:
                            print(f"[QC Launcher] Opening Interactive UI Window -> {url}")
                            _open_desktop_ui_window(url)
                            return
                    except Exception:
                        pass
                time.sleep(0.25)

        threading.Thread(target=_delayed_open, daemon=True).start()

    print(f"[QC Launcher] Starting Local QC Server at {url} (Close window or Ctrl+C to stop)...")
    try:
        import uvicorn

        from backend.app.main import app as fastapi_app

        uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_level="info")
        return 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
