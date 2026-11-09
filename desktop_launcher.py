"""Standalone Windows Executable (.exe) Launcher for the Autonomous QC & Project Audit Intelligence Platform.

Compiled into `QC_Intelligence_Platform.exe` via PyInstaller.
When opened (double-clicked or run from terminal), it:
1. Ensures the local PostgreSQL 18 cluster (port 5433) is running.
2. Starts the FastAPI + Bundled React UI server on http://127.0.0.1:8000.
3. Opens the Interactive Project Upload, API Key & Instructions UI in a dedicated desktop window.
"""

import argparse
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
        s.settimeout(0.8)
        return s.connect_ex((host, port)) == 0


def _ensure_postgres_running(app_root: Path) -> None:
    if _is_port_open("127.0.0.1", 5433):
        print("[QC Launcher] PostgreSQL 18 is active on 127.0.0.1:5433.")
        return

    pg_exe = Path(r"C:\Program Files\PostgreSQL\18\bin\postgres.exe")
    pg_data = app_root / ".postgres_data"
    if pg_exe.exists() and pg_data.exists():
        print("[QC Launcher] Starting local PostgreSQL 18 cluster on port 5433...")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [str(pg_exe), "-D", str(pg_data), "-p", "5433"],
            cwd=str(app_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        for _ in range(24):
            if _is_port_open("127.0.0.1", 5433):
                print("[QC Launcher] PostgreSQL 18 started and accepting connections.")
                return
            time.sleep(0.4)


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


def _find_python_executable() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    candidates = [
        shutil.which("python"),
        str(Path.home() / r"AppData\Local\Programs\Python\Python311\python.exe"),
        str(Path.home() / r"AppData\Local\Programs\Python\Python312\python.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(Path(c).resolve())
    return "python"


def _http_status(url: str) -> int:
    req = urllib.request.Request(url, headers={"Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return int(resp.status)


def main() -> int:
    parser = argparse.ArgumentParser(description="QC Intelligence Platform Desktop .EXE Launcher")
    parser.add_argument(
        "--port", type=int, default=8000, help="Local port for the QC Platform UI & API"
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

    print("=" * 76)
    print("  AUTONOMOUS QC & PROJECT AUDIT INTELLIGENCE PLATFORM v1.0 (.EXE)")
    print("  Interactive Project Upload, API Key Setup, Readiness Advisor & Audit UI")
    print("=" * 76)
    print(f"[QC Launcher] Application Directory: {app_root}")

    _ensure_postgres_running(app_root)

    url = f"http://127.0.0.1:{args.port}"
    python_bin = _find_python_executable()

    if args.verify_startup:
        proc = None
        if not _is_port_open("127.0.0.1", args.port):
            proc = subprocess.Popen(
                [
                    python_bin,
                    "-m",
                    "uvicorn",
                    "backend.app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                ],
                cwd=str(app_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for _ in range(40):
                if _is_port_open("127.0.0.1", args.port):
                    break
                time.sleep(0.25)

        try:
            st_health = _http_status(f"{url}/api/v1/system/health")
            st_runtime = _http_status(f"{url}/api/v1/system/runtime-config")
            st_ui = _http_status(url)
            print(
                f"[QC Launcher] Verified EXE Startup! Health={st_health}, RuntimeConfig={st_runtime}, UI={st_ui}"
            )
            return 0 if (st_health == 200 and st_runtime == 200 and st_ui == 200) else 1
        finally:
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()

    if _is_port_open("127.0.0.1", args.port):
        print(f"[QC Launcher] QC Server is already running at {url}")
        if not args.no_browser:
            print(f"[QC Launcher] Opening Interactive UI Window -> {url}")
            _open_desktop_ui_window(url)
        return 0

    if not args.no_browser:
        def _delayed_open() -> None:
            for _ in range(40):
                if _is_port_open("127.0.0.1", args.port):
                    time.sleep(0.3)
                    print(f"[QC Launcher] Opening Interactive UI Window -> {url}")
                    _open_desktop_ui_window(url)
                    return
                time.sleep(0.25)

        threading.Thread(target=_delayed_open, daemon=True).start()

    print(f"[QC Launcher] Starting Local QC Server at {url} (Close window or Ctrl+C to stop)...")
    proc = subprocess.Popen(
        [
            python_bin,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        cwd=str(app_root),
    )
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
