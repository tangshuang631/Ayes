from ayes.app import menubar as menubar_app
from ayes.cli import menubar


def test_menubar_parser_accepts_base_url() -> None:
    parser = menubar.build_parser()
    args = parser.parse_args(["--base-url", "http://127.0.0.1:9999"])
    assert args.base_url == "http://127.0.0.1:9999"


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
    assert summary.target_line == "目标：进程 Safari"
    assert summary.roi_line == "ROI：全目标"
    assert summary.recent_line == "最近：命中监控关键词: OCR"
    assert len(summary.recent_tasks) == 2


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
    assert summary.target_line == "目标：窗口 企业微信"
    assert summary.recent_line == "最近命中：1719302400"


def test_recent_task_title_includes_mode_when_present() -> None:
    assert menubar_app._recent_task_title({"task_id": "task_1", "mode": "watch"}) == "task_1 · watch"
    assert menubar_app._recent_task_title({"task_id": "task_2"}) == "task_2"


def test_menubar_main_passes_base_url(monkeypatch) -> None:
    recorded = {}

    def fake_run_menu_bar(*, base_url: str) -> int:
        recorded["base_url"] = base_url
        return 0

    monkeypatch.setattr(menubar, "run_menu_bar", fake_run_menu_bar)
    exit_code = menubar.main(["--base-url", "http://127.0.0.1:9123"])

    assert exit_code == 0
    assert recorded["base_url"] == "http://127.0.0.1:9123"
