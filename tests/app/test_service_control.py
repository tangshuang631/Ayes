from pathlib import Path

import pytest

from ayes.app.service_control import ServiceConfig, ensure_service_started


def build_config(tmp_path: Path) -> ServiceConfig:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    return ServiceConfig(
        root_dir=tmp_path,
        runtime_dir=runtime_dir,
        pid_file=runtime_dir / "ayes-server.pid",
        monitor_pid_file=runtime_dir / "ayes-idle-monitor.pid",
        log_file=runtime_dir / "ayes-server.log",
        monitor_log_file=runtime_dir / "ayes-idle-monitor.log",
        host="127.0.0.1",
        port=8770,
        launcher_script=tmp_path / "scripts" / "run_ayes_service.py",
        python_bin="python3",
    )


def test_ensure_service_started_reuses_healthy_service_without_relaunch(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    config.pid_file.write_text("1234", encoding="utf-8")
    launches: list[str] = []

    result = ensure_service_started(
        config,
        health_check=lambda _config: True,
        pid_alive_check=lambda pid: pid == 1234,
        launch_callback=lambda _config: launches.append("launched"),
        wait_until_ready_callback=lambda _config: True,
    )

    assert result == "reused"
    assert launches == []


def test_ensure_service_started_refuses_duplicate_when_pid_alive_but_service_unhealthy(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    config.pid_file.write_text("5678", encoding="utf-8")
    launches: list[str] = []

    with pytest.raises(RuntimeError):
        ensure_service_started(
            config,
            health_check=lambda _config: False,
            pid_alive_check=lambda pid: pid == 5678,
            launch_callback=lambda _config: launches.append("launched"),
            wait_until_ready_callback=lambda _config: False,
        )

    assert launches == []


def test_ensure_service_started_launches_when_no_live_pid_and_waits_ready(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    launches: list[str] = []

    result = ensure_service_started(
        config,
        health_check=lambda _config: False,
        pid_alive_check=lambda pid: False,
        launch_callback=lambda _config: launches.append("launched"),
        wait_until_ready_callback=lambda _config: True,
    )

    assert result == "started"
    assert launches == ["launched"]


def test_ensure_service_started_reports_log_hint_when_launch_never_becomes_ready(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    config.log_file.write_text("ERROR: [Errno 1] error while attempting to bind on address", encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        ensure_service_started(
            config,
            health_check=lambda _config: False,
            pid_alive_check=lambda pid: False,
            launch_callback=lambda _config: None,
            wait_until_ready_callback=lambda _config: False,
        )

    assert "未在预期时间内就绪" in str(excinfo.value)
    assert "bind on address" in str(excinfo.value)
