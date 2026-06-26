from ayes.app import menubar as menubar_app
from ayes.cli import menubar
from ayes.cli import agent_tool
from pathlib import Path


def test_menubar_parser_accepts_base_url() -> None:
    parser = menubar.build_parser()
    args = parser.parse_args(["--base-url", "http://127.0.0.1:9999"])
    assert args.base_url == "http://127.0.0.1:9999"


def test_agent_tool_load_spec_defaults_sampling_to_six_seconds() -> None:
    parser = agent_tool.build_parser()
    args = parser.parse_args(["load-spec", "--task-id", "task", "--target-type", "screen"])

    assert args.screenshot_interval_ms == 6000
    assert args.ocr_interval_ms == 6000
    assert args.change_detection_interval_ms == 6000


def test_agent_tool_sampling_command_posts_interval_seconds(monkeypatch) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded.update({"base_url": base_url, "path": path, "method": method, "payload": payload})
        return {"status": "ok"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    args = agent_tool.build_parser().parse_args(["sampling", "--interval-sec", "2.5"])

    assert agent_tool._dispatch(args) == {"status": "ok"}
    assert recorded["path"] == "/api/control/sampling"
    assert recorded["method"] == "POST"
    assert recorded["payload"] == {"interval_ms": 2500.0}


def test_build_menu_bar_summary_for_idle_state() -> None:
    summary = menubar_app.build_menu_bar_summary(
        {
            "is_paused": False,
            "has_runner": False,
            "is_running": False,
            "task_id": None,
            "target": None,
            "task_context": {"recent_tasks": []},
        }
    )

    assert summary.title == "Ayes·Idle"
    assert summary.icon_glyph == "◌"
    assert summary.state_line == "空闲"
    assert summary.task_line == "任务：无任务"
    assert summary.target_line == "目标：未设置"
    assert summary.recent_line == "最近：暂无"


def test_build_menu_bar_summary_for_running_process_task() -> None:
    summary = menubar_app.build_menu_bar_summary(
        {
            "is_paused": False,
            "has_runner": True,
            "is_running": True,
            "task_id": "task_watch_safari",
            "target": {"type": "process", "process_name": "Safari"},
            "latest_key_event": {"summary": "命中监控关键词: OCR"},
            "task_context": {
                "recent_tasks": [
                    {"task_id": "task_watch_safari", "mode": "watch", "is_current": True},
                    {"task_id": "task_watch_wechat", "mode": "watch", "is_current": False},
                ]
            },
        }
    )

    assert summary.title == "Ayes·Live"
    assert summary.icon_glyph == "◉"
    assert summary.state_line == "监控中"
    assert summary.task_line == "任务：task_watch_safari"
    assert summary.target_line == "目标：进程监控 Safari"
    assert summary.roi_line == "ROI：全目标"
    assert summary.recent_line == "最近：命中监控关键词: OCR"
    assert len(summary.recent_tasks) == 2


def test_status_fallback_title_uses_short_icon_not_long_text() -> None:
    summary = menubar_app.build_menu_bar_summary(
        {
            "is_paused": False,
            "has_runner": True,
            "is_running": True,
            "task_id": "task_watch_safari",
            "target": {"type": "process", "process_name": "Safari"},
            "task_context": {"recent_tasks": []},
        }
    )

    assert menubar_app._fallback_status_title(summary) == "◉"


def test_build_menu_bar_summary_includes_current_roi_list() -> None:
    summary = menubar_app.build_menu_bar_summary(
        {
            "is_paused": False,
            "has_runner": True,
            "is_running": True,
            "task_id": "task_roi",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {"region_id": "roi_price", "name": "价格区", "enabled": True},
                    {"region_id": "roi_stock", "name": "库存区", "enabled": True},
                    {"region_id": "roi_disabled", "name": "停用区", "enabled": False},
                ],
            },
            "task_context": {"recent_tasks": []},
        }
    )

    assert summary.roi_line == "ROI：价格区 / 库存区"
    assert summary.roi_regions == [
        {"region_id": "roi_price", "name": "价格区", "enabled": True},
        {"region_id": "roi_stock", "name": "库存区", "enabled": True},
    ]


def test_build_menu_bar_summary_for_paused_window_task() -> None:
    summary = menubar_app.build_menu_bar_summary(
        {
            "is_paused": True,
            "has_runner": True,
            "is_running": False,
            "task_id": "task_window",
            "target": {"type": "window", "window_title": "企业微信"},
            "last_match_at": 1719302400.0,
            "task_context": {"recent_tasks": []},
        }
    )

    assert summary.title == "Ayes·Paused"
    assert summary.icon_glyph == "◐"
    assert summary.state_line == "已暂停"
    assert summary.target_line == "目标：窗口监控 企业微信"
    assert summary.recent_line == "最近命中：1719302400"


def test_recent_task_title_includes_mode_when_present() -> None:
    assert menubar_app._recent_task_title({"task_id": "task_1", "mode": "watch"}) == "task_1 · watch"
    assert menubar_app._recent_task_title({"task_id": "task_2"}) == "task_2"


def test_recent_task_title_includes_fullscreen_monitor_type() -> None:
    assert (
        menubar_app._recent_task_title(
            {
                "task_id": "2026-06-26_screen_monitor",
                "target": {"type": "screen", "screen_id": 1},
            }
        )
        == "2026-06-26_screen_monitor · 全屏监控 · 屏幕 1"
    )


def test_recent_task_title_includes_process_monitor_name_and_summary() -> None:
    assert (
        menubar_app._recent_task_title(
            {
                "task_id": "task_chrome",
                "target": {"type": "process", "process_name": "Chrome", "window_title": "Apifox 登录页"},
            }
        )
        == "task_chrome · 进程监控 · Chrome · Apifox 登录页"
    )


def test_recent_task_title_includes_roi_child_task_name() -> None:
    assert (
        menubar_app._recent_task_title(
            {
                "task_id": "2026-06-26_process_monitor_Chrome__roi_price",
                "mode": "observe",
                "target": {"type": "process", "process_name": "Chrome"},
                "roi": {"roi_name": "价格监控"},
            }
        )
        == "2026-06-26_process_monitor_Chrome__roi_price · ROI · 价格监控"
    )


def test_native_menubar_source_exposes_roi_tree_and_task_start_actions() -> None:
    source = agent_tool._build_native_menubar_source(
        base_url="http://127.0.0.1:8770",
        runtime_dir=Path("/tmp/ayes-runtime"),
    )

    assert "启动 / 继续此任务" in source
    assert "设定 ROI..." in source
    assert "ROI 子任务" in source
    assert "openRoiEditor:" in source
    assert "startTask:" in source
    assert "/api/tasks/\" stringByAppendingFormat:@\"%@/roi\"" in source


def test_native_menubar_source_explicitly_pops_menu_on_click() -> None:
    source = agent_tool._build_native_menubar_source(
        base_url="http://127.0.0.1:8770",
        runtime_dir=Path("/tmp/ayes-runtime"),
    )

    assert "@selector(showMenu:)" in source
    assert "sendActionOn:" in source
    assert "popUpStatusItemMenu:self.menu" in source


def test_python_menubar_uses_continue_last_monitor_label() -> None:
    source = menubar_app.__file__
    assert source is not None
    with open(source, encoding="utf-8") as file:
        content = file.read()
    assert "继续上次的监控" in content
    assert "恢复监控" not in content


def test_installed_menubar_wrapper_uses_native_agent_tool_launcher() -> None:
    wrapper = agent_tool.__file__
    assert wrapper is not None
    source = Path("/Users/apple/Desktop/2026/Ayes/scripts/install_ayes_local_skill.py").read_text(encoding="utf-8")
    assert "ayes.cli.agent_tool control menubar" in source
    assert "ayes.cli.menubar" not in source[source.index("def build_menubar_wrapper_script") :]


def test_parse_interval_seconds_accepts_half_second_to_one_hour() -> None:
    assert menubar_app._parse_interval_seconds("0.5") == 500
    assert menubar_app._parse_interval_seconds("3") == 3000
    assert menubar_app._parse_interval_seconds("3600") == 3600000


def test_parse_interval_seconds_rejects_out_of_range_values() -> None:
    for raw in ["0.49", "3600.1", "abc"]:
        try:
            menubar_app._parse_interval_seconds(raw)
        except ValueError:
            continue
        raise AssertionError(f"expected {raw} to be rejected")


def test_parse_hotkey_accepts_safe_combo() -> None:
    hotkey = menubar_app.parse_hotkey("cmd+shift+9")

    assert hotkey is not None
    assert hotkey.canonical == "cmd+shift+9"
    assert hotkey.key == "9"
    assert hotkey.modifiers == frozenset({"cmd", "shift"})


def test_parse_hotkey_rejects_dangerous_or_incomplete_combo() -> None:
    for raw in ["cmd+v", "cmd+c", "shift+9", "cmd+shift", "cmd+q", "abc"]:
        try:
            menubar_app.parse_hotkey(raw)
        except ValueError:
            continue
        raise AssertionError(f"expected {raw} to be rejected")


def test_latest_frame_hotkey_requires_running_task() -> None:
    assert menubar_app.should_handle_latest_frame_hotkey({"is_running": True, "has_runner": True}) is True
    assert menubar_app.should_handle_latest_frame_hotkey({"is_running": False, "has_runner": True}) is False
    assert menubar_app.should_handle_latest_frame_hotkey({"is_running": True, "has_runner": False}) is False


def test_resolve_screenshot_path_maps_runtime_relative_path_to_data_dir() -> None:
    assert (
        menubar_app._resolve_screenshot_path(
            "runtime/latest/latest-frame.png",
            {"data_dir": "/Users/apple/.codex/skills/ayes-local/runtime"},
        )
        == "/Users/apple/.codex/skills/ayes-local/runtime/latest/latest-frame.png"
    )


def test_format_hotkey_action_message_reports_action_result() -> None:
    assert menubar_app._format_hotkey_action_message("copied") == "已复制并粘贴最新采样图"
    assert menubar_app._format_hotkey_action_message("not_running") == "当前没有正在监控的任务"
    assert menubar_app._format_hotkey_action_message("missing_screenshot") == "没有找到最新采样图"


def test_menubar_main_passes_base_url(monkeypatch) -> None:
    recorded = {}

    def fake_run_menu_bar(*, base_url: str) -> int:
        recorded["base_url"] = base_url
        return 0

    monkeypatch.setattr(menubar, "run_menu_bar", fake_run_menu_bar)
    exit_code = menubar.main(["--base-url", "http://127.0.0.1:9123"])

    assert exit_code == 0
    assert recorded["base_url"] == "http://127.0.0.1:9123"
