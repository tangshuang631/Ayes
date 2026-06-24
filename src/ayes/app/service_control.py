"""Service lifecycle helpers for the local Ayes background process."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import signal
import subprocess
import sys
import time
from typing import Callable, Literal, Optional
from urllib.error import URLError
from urllib.request import urlopen


EnsureResult = Literal["reused", "started"]


@dataclass(frozen=True)
class ServiceConfig:
    root_dir: Path
    runtime_dir: Path
    pid_file: Path
    monitor_pid_file: Path
    log_file: Path
    monitor_log_file: Path
    host: str
    port: int
    launcher_script: Path
    python_bin: str = sys.executable

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def status_url(self) -> str:
        return f"{self.base_url}/api/status"

    @property
    def shutdown_gate_url(self) -> str:
        return f"{self.base_url}/api/app/can-shutdown"


def default_service_config(root_dir: Optional[Path] = None) -> ServiceConfig:
    resolved_root = (root_dir or Path(__file__).resolve().parents[3]).resolve()
    runtime_dir = resolved_root / "runtime"
    return ServiceConfig(
        root_dir=resolved_root,
        runtime_dir=runtime_dir,
        pid_file=runtime_dir / "ayes-server.pid",
        monitor_pid_file=runtime_dir / "ayes-idle-monitor.pid",
        log_file=runtime_dir / "ayes-server.log",
        monitor_log_file=runtime_dir / "ayes-idle-monitor.log",
        host="127.0.0.1",
        port=8770,
        launcher_script=resolved_root / "scripts" / "run_ayes_service.py",
        python_bin=os.environ.get("PYTHON_BIN", sys.executable),
    )


def read_pid(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def is_pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cleanup_stale_pid(path: Path, *, pid_alive_check: Callable[[Optional[int]], bool] = is_pid_alive) -> None:
    pid = read_pid(path)
    if pid is None or not pid_alive_check(pid):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def is_service_healthy(config: ServiceConfig, *, timeout_sec: float = 1.0) -> bool:
    try:
        with urlopen(config.status_url, timeout=timeout_sec) as response:
            return response.status == 200
    except (URLError, OSError, TimeoutError):
        return False


def wait_until_ready(config: ServiceConfig, *, attempts: int = 40, sleep_sec: float = 1.0) -> bool:
    for _ in range(attempts):
        if is_service_healthy(config):
            return True
        time.sleep(sleep_sec)
    return False


def launch_service(config: ServiceConfig) -> None:
    subprocess.run(
        [config.python_bin, str(config.launcher_script)],
        cwd=str(config.root_dir),
        check=True,
    )


def ensure_service_started(
    config: ServiceConfig,
    *,
    health_check: Callable[[ServiceConfig], bool] = is_service_healthy,
    pid_alive_check: Callable[[Optional[int]], bool] = is_pid_alive,
    launch_callback: Callable[[ServiceConfig], None] = launch_service,
    wait_until_ready_callback: Callable[[ServiceConfig], bool] = wait_until_ready,
) -> EnsureResult:
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_pid(config.pid_file, pid_alive_check=pid_alive_check)

    if health_check(config):
        return "reused"

    existing_pid = read_pid(config.pid_file)
    if pid_alive_check(existing_pid):
        raise RuntimeError(f"Ayes 后台进程 {existing_pid} 仍存活，但服务健康检查失败，拒绝重复拉起实例。")

    launch_callback(config)
    if not wait_until_ready_callback(config):
        raise RuntimeError("Ayes 后台服务启动后未在预期时间内就绪。")
    return "started"


def stop_pid(pid: Optional[int]) -> None:
    if not is_pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def can_shutdown_service(config: ServiceConfig, *, timeout_sec: float = 1.0) -> bool:
    try:
        with urlopen(config.shutdown_gate_url, timeout=timeout_sec) as response:
            payload = response.read().decode("utf-8")
            return '"can_shutdown_service":true' in payload.replace(" ", "")
    except (URLError, OSError, TimeoutError):
        return False


def start_idle_monitor(config: ServiceConfig, *, idle_timeout_sec: int) -> Optional[int]:
    cleanup_stale_pid(config.monitor_pid_file)
    existing_monitor_pid = read_pid(config.monitor_pid_file)
    if is_pid_alive(existing_monitor_pid):
        return existing_monitor_pid

    env = os.environ.copy()
    env["AYES_IDLE_TIMEOUT_SEC"] = str(idle_timeout_sec)
    monitor_code = (
        "from ayes.app.service_control import default_service_config, run_idle_monitor; "
        "run_idle_monitor(default_service_config())"
    )
    process = subprocess.Popen(
        [config.python_bin, "-c", monitor_code],
        cwd=str(config.root_dir),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=config.monitor_log_file.open("ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    config.monitor_pid_file.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def run_idle_monitor(config: ServiceConfig) -> None:
    idle_timeout_sec = max(int(os.environ.get("AYES_IDLE_TIMEOUT_SEC", "120")), 1)
    while True:
        server_pid = read_pid(config.pid_file)
        if not is_pid_alive(server_pid):
            cleanup_stale_pid(config.pid_file)
            cleanup_stale_pid(config.monitor_pid_file)
            return
        if can_shutdown_service(config):
            time.sleep(idle_timeout_sec)
            if can_shutdown_service(config):
                stop_pid(server_pid)
                cleanup_stale_pid(config.pid_file)
                cleanup_stale_pid(config.monitor_pid_file)
                return
        time.sleep(5)
