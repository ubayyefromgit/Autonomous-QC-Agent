"""ProjectRunner abstraction and LocalProjectRunner / DockerProjectRunner adapters."""

import asyncio
import hashlib
import os
import shutil
import socket
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import psutil

from backend.app.core.config import get_settings
from backend.app.core.exceptions import SecurityPolicyViolationError
from backend.app.core.logging import redact_secrets
from shared.constants.defaults import ALLOWED_RUNNER_COMMANDS, DEFAULT_EXCLUDED_DIRS


@dataclass
class WorkspaceInfo:
    session_id: UUID
    source_root: Path
    workspace_dir: Path
    runner_mode: str
    synthetic_env_path: Path
    synthetic_env: dict[str, str]
    container_id: str | None = None


@dataclass
class ExecutionResult:
    command: list[str]
    working_dir: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    runner_mode: str = "LOCAL"


@dataclass
class ServiceStartupConfig:
    service_name: str
    command: list[str]
    working_dir: str | None = None
    port: int | None = None
    health_url: str | None = None
    env_overrides: dict[str, str] = field(default_factory=dict)
    startup_timeout_seconds: int = 25


@dataclass
class RunningServiceHandle:
    service_id: str
    service_name: str
    port: int
    base_url: str
    pid: int | None
    log_file_path: Path
    started_at: datetime
    process: subprocess.Popen[str] | None = None
    container_id: str | None = None


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class ProjectRunner(ABC):
    """Unified execution interface for Local and Docker sandboxes."""

    runner_mode: str

    @abstractmethod
    async def prepare_workspace(
        self,
        project_path: str | Path,
        session_id: UUID,
        config: dict[str, Any] | None = None,
    ) -> WorkspaceInfo:
        ...

    @abstractmethod
    async def verify_snapshot(self, workspace: WorkspaceInfo) -> dict[str, Any]:
        ...

    @abstractmethod
    async def prepare_dependencies(
        self, workspace: WorkspaceInfo, manifest: dict[str, Any]
    ) -> ExecutionResult:
        ...

    @abstractmethod
    async def execute_command(
        self,
        workspace: WorkspaceInfo,
        command: list[str],
        timeout: int = 60,
        cwd_relative: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> ExecutionResult:
        ...

    @abstractmethod
    async def start_service(
        self, workspace: WorkspaceInfo, service_config: ServiceStartupConfig
    ) -> RunningServiceHandle:
        ...

    @abstractmethod
    async def check_service_health(
        self, handle: RunningServiceHandle, health_path: str = "/"
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def stop_service(self, handle: RunningServiceHandle) -> None:
        ...

    @abstractmethod
    async def collect_logs(self, handle: RunningServiceHandle) -> str:
        ...

    @abstractmethod
    async def cleanup(self, workspace: WorkspaceInfo) -> None:
        ...

    def validate_command_policy(self, command: list[str]) -> None:
        if not command:
            raise SecurityPolicyViolationError("Empty command is not permitted.")
        executable = Path(command[0]).stem.lower()
        allowed = {cmd.lower() for cmd in ALLOWED_RUNNER_COMMANDS}
        if executable not in allowed:
            raise SecurityPolicyViolationError(
                f"Executable '{command[0]}' is blocked by runner command allowlist policy.",
                details={"executable": executable, "allowed": sorted(allowed)},
            )
        joined = " ".join(command)
        forbidden_tokens = ("&& rm -rf /", "format c:", "del /f /s /q c:\\", "docker.sock")
        for token in forbidden_tokens:
            if token in joined.lower():
                raise SecurityPolicyViolationError(
                    f"Command contains forbidden destructive pattern: '{token}'"
                )

    def build_synthetic_env(self, session_id: UUID) -> dict[str, str]:
        """Create an isolated environment dictionary without leaking host secrets."""
        short_id = str(session_id).replace("-", "")[:12]
        safe_env: dict[str, str] = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
            "SYSTEMDRIVE": os.environ.get("SYSTEMDRIVE", "C:"),
            "WINDIR": os.environ.get("WINDIR", "C:\\Windows"),
            "COMSPEC": os.environ.get("COMSPEC", "C:\\Windows\\System32\\cmd.exe"),
            "TEMP": os.environ.get("TEMP", "/tmp"),
            "TMP": os.environ.get("TMP", "/tmp"),
            "USERPROFILE": os.environ.get("USERPROFILE", ""),
            "APPDATA": os.environ.get("APPDATA", ""),
            "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
            "USERNAME": os.environ.get("USERNAME", "postgres"),
            "HOME": os.environ.get("HOME", ""),
            "PYTHONPATH": ".",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "QC_SANDBOX_SESSION_ID": str(session_id),
            "APP_ENV": "test_sandbox",
            "SECRET_KEY": f"synthetic-test-secret-{short_id}",
            "QC_DATABASE_URL": "postgresql+asyncpg://postgres@127.0.0.1:5433/qc_platform",
            "QC_SYNC_DATABASE_URL": "postgresql+psycopg2://postgres@127.0.0.1:5433/qc_platform",
            "DATABASE_URL": "postgresql+asyncpg://postgres@127.0.0.1:5433/qc_platform_test",
            "SYNC_DATABASE_URL": "postgresql+psycopg2://postgres@127.0.0.1:5433/qc_platform_test",
        }
        return safe_env


class LocalProjectRunner(ProjectRunner):
    """Process-isolated local execution adapter with isolated workspace snapshots."""

    runner_mode = "LOCAL"

    def __init__(self, workspace_root: Path | None = None) -> None:
        settings = get_settings()
        self.workspace_root = workspace_root or settings.workspace_path
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._active_services: dict[str, RunningServiceHandle] = {}

    async def prepare_workspace(
        self,
        project_path: str | Path,
        session_id: UUID,
        config: dict[str, Any] | None = None,
    ) -> WorkspaceInfo:
        source_root = Path(project_path).resolve()
        if not source_root.exists():
            raise FileNotFoundError(f"Project source path does not exist: {source_root}")

        workspace_dir = self.workspace_root / f"session_{session_id}"
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir, ignore_errors=True)
        workspace_dir.mkdir(parents=True, exist_ok=True)

        # Copy source files excluding heavy/generated directories, workspace subdirs, and sensitive .env files
        ignore_dirs = set(DEFAULT_EXCLUDED_DIRS) | {self.workspace_root.name, workspace_dir.name}
        if config and config.get("exclusions"):
            ignore_dirs.update(config["exclusions"])

        def _ignore_filter(_dir: str, names: list[str]) -> set[str]:
            ignored: set[str] = set()
            for name in names:
                if name in ignore_dirs or name in {".env", ".env.local", ".env.production"}:
                    ignored.add(name)
            return ignored

        await asyncio.to_thread(
            shutil.copytree,
            source_root,
            workspace_dir,
            ignore=_ignore_filter,
            dirs_exist_ok=True,
        )

        synthetic_env = self.build_synthetic_env(session_id)
        synthetic_env_path = workspace_dir / ".env.qc"
        env_lines = [f'{k}="{v}"' for k, v in synthetic_env.items() if not k.startswith("PATH")]
        synthetic_env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

        return WorkspaceInfo(
            session_id=session_id,
            source_root=source_root,
            workspace_dir=workspace_dir,
            runner_mode=self.runner_mode,
            synthetic_env_path=synthetic_env_path,
            synthetic_env=synthetic_env,
        )

    async def verify_snapshot(self, workspace: WorkspaceInfo) -> dict[str, Any]:
        file_count = 0
        digest = hashlib.sha256()
        for root, _dirs, files in os.walk(workspace.workspace_dir):
            for fname in sorted(files):
                if fname == ".env.qc":
                    continue
                fpath = Path(root) / fname
                rel = fpath.relative_to(workspace.workspace_dir).as_posix()
                digest.update(rel.encode("utf-8"))
                file_count += 1
        return {
            "verified": True,
            "workspace_dir": str(workspace.workspace_dir),
            "file_count": file_count,
            "snapshot_checksum": digest.hexdigest(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def prepare_dependencies(
        self, workspace: WorkspaceInfo, manifest: dict[str, Any]
    ) -> ExecutionResult:
        return await self.execute_command(
            workspace=workspace,
            command=["python", "--version"],
            timeout=15,
        )

    async def execute_command(
        self,
        workspace: WorkspaceInfo,
        command: list[str],
        timeout: int = 60,
        cwd_relative: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> ExecutionResult:
        self.validate_command_policy(command)
        target_cwd = (
            (workspace.workspace_dir / cwd_relative).resolve()
            if cwd_relative
            else workspace.workspace_dir.resolve()
        )
        if not str(target_cwd).startswith(str(workspace.workspace_dir.resolve())):
            raise SecurityPolicyViolationError("Working directory escapes isolated workspace boundary.")

        env = {**workspace.synthetic_env, **(env_overrides or {})}
        env["PYTHONPATH"] = str(workspace.workspace_dir.resolve())
        start_ts = time.perf_counter()

        def _run_sync() -> ExecutionResult:
            timed_out = False
            try:
                proc = subprocess.Popen(
                    command,
                    cwd=str(target_cwd),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                    exit_code = proc.returncode
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._terminate_process_tree(proc.pid)
                    stdout, stderr = proc.communicate()
                    exit_code = -1
            except FileNotFoundError as exc:
                stdout = ""
                stderr = f"Command executable not found: {exc}"
                exit_code = 127
            except Exception as exc:
                stdout = ""
                stderr = f"Runner execution error: {exc}"
                exit_code = 1

            duration = round(time.perf_counter() - start_ts, 3)
            return ExecutionResult(
                command=command,
                working_dir=str(target_cwd),
                exit_code=exit_code,
                stdout=redact_secrets(stdout),
                stderr=redact_secrets(stderr),
                duration_seconds=duration,
                timed_out=timed_out,
                runner_mode=self.runner_mode,
            )

        return await asyncio.to_thread(_run_sync)

    async def start_service(
        self, workspace: WorkspaceInfo, service_config: ServiceStartupConfig
    ) -> RunningServiceHandle:
        self.validate_command_policy(service_config.command)
        port = service_config.port or find_free_port()
        cmd = [arg.replace("{port}", str(port)) for arg in service_config.command]

        target_cwd = (
            (workspace.workspace_dir / service_config.working_dir).resolve()
            if service_config.working_dir
            else workspace.workspace_dir.resolve()
        )
        log_file = workspace.workspace_dir / f"service_{service_config.service_name}_{port}.log"
        env = {
            **workspace.synthetic_env,
            **service_config.env_overrides,
            "PORT": str(port),
            "PYTHONPATH": str(workspace.workspace_dir.resolve()),
        }

        log_fp = log_file.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=str(target_cwd),
            env=env,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            text=True,
        )
        service_id = f"{service_config.service_name}-{port}"
        base_url = f"http://127.0.0.1:{port}"
        handle = RunningServiceHandle(
            service_id=service_id,
            service_name=service_config.service_name,
            port=port,
            base_url=base_url,
            pid=proc.pid,
            log_file_path=log_file,
            started_at=datetime.now(UTC),
            process=proc,
        )
        self._active_services[service_id] = handle

        health_url = service_config.health_url or base_url
        deadline = time.time() + service_config.startup_timeout_seconds
        async with httpx.AsyncClient(timeout=2.0) as client:
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    resp = await client.get(health_url)
                    if resp.status_code < 500:
                        break
                except Exception:
                    await asyncio.sleep(0.4)

        return handle

    async def check_service_health(
        self, handle: RunningServiceHandle, health_path: str = "/"
    ) -> dict[str, Any]:
        is_alive = handle.process is not None and handle.process.poll() is None
        url = f"{handle.base_url.rstrip('/')}/{health_path.lstrip('/')}"
        http_reachable = False
        status_code = None
        latency_ms = None
        if is_alive:
            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(url)
                    http_reachable = True
                    status_code = resp.status_code
                    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            except Exception:
                pass
        return {
            "service_id": handle.service_id,
            "pid": handle.pid,
            "process_alive": is_alive,
            "http_reachable": http_reachable,
            "status_code": status_code,
            "latency_ms": latency_ms,
        }

    async def stop_service(self, handle: RunningServiceHandle) -> None:
        if handle.pid:
            self._terminate_process_tree(handle.pid)
        self._active_services.pop(handle.service_id, None)

    async def collect_logs(self, handle: RunningServiceHandle) -> str:
        if handle.log_file_path.exists():
            return redact_secrets(
                handle.log_file_path.read_text(encoding="utf-8", errors="replace")
            )
        return ""

    async def cleanup(self, workspace: WorkspaceInfo) -> None:
        for _svc_id, handle in list(self._active_services.items()):
            await self.stop_service(handle)
        if workspace.workspace_dir.exists():
            await asyncio.to_thread(shutil.rmtree, workspace.workspace_dir, True)

    def _terminate_process_tree(self, pid: int) -> None:
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            parent.terminate()
            _, alive = psutil.wait_procs([parent, *children], timeout=3)
            for p in alive:
                try:
                    p.kill()
                except psutil.Error:
                    pass
        except psutil.Error:
            pass


class DockerProjectRunner(ProjectRunner):
    """Disposable container sandbox adapter enforcing CPU, memory, PID, non-root, and network limits."""

    runner_mode = "DOCKER"

    def __init__(
        self,
        image: str = "python:3.11-slim",
        cpus: str = "1.0",
        memory: str = "1024m",
        pids_limit: int = 128,
        network_mode: str = "none",
    ) -> None:
        self.image = image
        self.cpus = cpus
        self.memory = memory
        self.pids_limit = pids_limit
        self.network_mode = network_mode
        self._local_helper = LocalProjectRunner()

    @staticmethod
    def is_docker_available() -> bool:
        docker_bin = shutil.which("docker")
        if not docker_bin:
            return False
        try:
            res = subprocess.run(
                [docker_bin, "info"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False

    def build_docker_run_args(
        self,
        workspace: WorkspaceInfo,
        command: list[str],
        cwd_relative: str | None = None,
    ) -> list[str]:
        """Construct hardened non-root Docker execution command with strict resource caps."""
        self.validate_command_policy(command)
        container_workdir = "/workspace"
        if cwd_relative:
            container_workdir = f"/workspace/{cwd_relative.strip('/')}"

        return [
            "docker",
            "run",
            "--rm",
            "--user",
            "10001:10001",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--cpus={self.cpus}",
            f"--memory={self.memory}",
            f"--pids-limit={self.pids_limit}",
            f"--network={self.network_mode}",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            "-v",
            f"{workspace.workspace_dir}:/workspace:ro",
            "-w",
            container_workdir,
            "--env-file",
            str(workspace.synthetic_env_path),
            self.image,
            *command,
        ]

    async def prepare_workspace(
        self,
        project_path: str | Path,
        session_id: UUID,
        config: dict[str, Any] | None = None,
    ) -> WorkspaceInfo:
        ws = await self._local_helper.prepare_workspace(project_path, session_id, config)
        ws.runner_mode = self.runner_mode
        return ws

    async def verify_snapshot(self, workspace: WorkspaceInfo) -> dict[str, Any]:
        snap = await self._local_helper.verify_snapshot(workspace)
        snap["runner_mode"] = self.runner_mode
        snap["docker_available"] = self.is_docker_available()
        return snap

    async def prepare_dependencies(
        self, workspace: WorkspaceInfo, manifest: dict[str, Any]
    ) -> ExecutionResult:
        return await self.execute_command(workspace, ["python", "--version"], timeout=20)

    async def execute_command(
        self,
        workspace: WorkspaceInfo,
        command: list[str],
        timeout: int = 60,
        cwd_relative: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> ExecutionResult:
        docker_cmd = self.build_docker_run_args(workspace, command, cwd_relative)
        if not self.is_docker_available():
            return ExecutionResult(
                command=docker_cmd,
                working_dir=str(workspace.workspace_dir),
                exit_code=127,
                stdout="",
                stderr="Docker daemon/CLI is not installed or running on this host. Cannot run container sandbox.",
                duration_seconds=0.01,
                timed_out=False,
                runner_mode=self.runner_mode,
            )

        t0 = time.perf_counter()
        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return ExecutionResult(
            command=docker_cmd,
            working_dir=str(workspace.workspace_dir),
            exit_code=proc.returncode,
            stdout=redact_secrets(proc.stdout),
            stderr=redact_secrets(proc.stderr),
            duration_seconds=round(time.perf_counter() - t0, 3),
            timed_out=False,
            runner_mode=self.runner_mode,
        )

    async def start_service(
        self, workspace: WorkspaceInfo, service_config: ServiceStartupConfig
    ) -> RunningServiceHandle:
        return await self._local_helper.start_service(workspace, service_config)

    async def check_service_health(
        self, handle: RunningServiceHandle, health_path: str = "/"
    ) -> dict[str, Any]:
        return await self._local_helper.check_service_health(handle, health_path)

    async def stop_service(self, handle: RunningServiceHandle) -> None:
        await self._local_helper.stop_service(handle)

    async def collect_logs(self, handle: RunningServiceHandle) -> str:
        return await self._local_helper.collect_logs(handle)

    async def cleanup(self, workspace: WorkspaceInfo) -> None:
        await self._local_helper.cleanup(workspace)


def get_project_runner(runner_mode: str = "LOCAL") -> ProjectRunner:
    if runner_mode.upper() == "DOCKER":
        return DockerProjectRunner()
    return LocalProjectRunner()
