import pytest

from ayes.config.models import ConfigError, WatchSpec


def test_triggered_spec_parses_complete_config() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "triggered",
            "target": {
                "type": "process",
                "process_name": "TargetApp",
            },
            "sampling": {
                "screenshot_interval_ms": 500,
                "ocr_interval_ms": 1000,
                "change_detection_interval_ms": 500,
                "max_fps": 2,
                "skip_ocr_when_no_change": True,
            },
            "memory": {
                "short_term": {"retain_minutes": 15},
                "long_term": {"retain_hours": 24, "max_retain_hours": 72},
            },
            "watch_intent": {
                "enabled": True,
                "summary": "价格低于阈值时提醒我",
                "queries": ["价格低于 299"],
                "rules": [
                    {
                        "type": "numeric_threshold",
                        "field": "price",
                        "operator": "lt",
                        "value": 299,
                        "unit": "cny",
                    }
                ],
            },
            "alert": {
                "enabled": True,
                "channel": "wecom_webhook",
                "webhook_url_env": "AYES_WECOM_WEBHOOK_URL",
            },
            "actions": {
                "refresh_click": {
                    "enabled": True,
                    "point": {"x": 100, "y": 200},
                    "coordinate_space": "window",
                }
            },
        }
    )
    assert spec.mode == "triggered"
    assert spec.target.process_name == "TargetApp"
    assert spec.actions.refresh_click.enabled is True
    assert spec.watch_intent.rules[0].operator == "lt"


def test_observe_mode_can_disable_watch_intent() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    assert spec.watch_intent.enabled is False
    assert spec.memory.short_term.retain_minutes == 15


def test_short_term_memory_rejects_more_than_fifteen_minutes() -> None:
    with pytest.raises(ConfigError):
        WatchSpec.from_dict(
            {
                "spec_version": "1.0",
                "mode": "observe",
                "target": {"type": "screen", "screen_id": 1},
                "memory": {"short_term": {"retain_minutes": 16}},
            }
        )


def test_triggered_mode_requires_watch_intent_enabled() -> None:
    with pytest.raises(ConfigError):
        WatchSpec.from_dict(
            {
                "spec_version": "1.0",
                "mode": "triggered",
                "target": {"type": "window", "window_id": 101},
                "watch_intent": {"enabled": False},
            }
        )


def test_process_target_can_bind_by_process_name() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "Safari"},
            "watch_intent": {"enabled": False},
        }
    )
    assert spec.target.type == "process"
    assert spec.target.process_name == "Safari"


def test_watch_spec_supports_multi_regions_and_vision_config() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_main",
                        "name": "价格区",
                        "x": 120,
                        "y": 240,
                        "w": 300,
                        "h": 120,
                        "coordinate_space": "target",
                        "enabled": True,
                    },
                    {
                        "region_id": "roi_chart",
                        "name": "图表区",
                        "x": 450,
                        "y": 240,
                        "w": 280,
                        "h": 180,
                        "coordinate_space": "target",
                        "enabled": True,
                    },
                ],
            },
            "vision": {
                "enabled": True,
                "provider": "ollama",
                "model": "qwen2.5vl:7b",
                "trigger_when_ocr_sparse": True,
                "ocr_sparse_min_chars": 10,
                "disable_for_text_only_tasks": True,
                "disable_for_numeric_only_tasks": True,
                "disable_for_threshold_rules": True,
                "sampling_every_n_runs": 3,
                "sampling_min_interval_sec": 20,
            },
            "watch_intent": {"enabled": False},
        }
    )
    assert len(spec.target.regions) == 2
    assert spec.target.regions[0].region_id == "roi_main"
    assert spec.vision.enabled is True
    assert spec.vision.model == "qwen2.5vl:7b"
    assert spec.vision.disable_for_text_only_tasks is True
    assert spec.vision.disable_for_numeric_only_tasks is True
    assert spec.vision.disable_for_threshold_rules is True
    assert spec.vision.sampling_every_n_runs == 3
    assert spec.vision.sampling_min_interval_sec == 20


def test_alert_config_accepts_direct_webhook_url_for_local_smoke() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "triggered",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": True, "queries": ["Codex"]},
            "alert": {
                "enabled": True,
                "channel": "wecom_webhook",
                "webhook_url": "http://127.0.0.1:18999/webhook",
            },
        }
    )
    assert spec.alert.enabled is True
    assert spec.alert.webhook_url == "http://127.0.0.1:18999/webhook"


def test_alert_config_accepts_custom_message_template() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "triggered",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": True, "queries": ["库存恢复"]},
            "alert": {
                "enabled": True,
                "channel": "wecom_webhook",
                "webhook_url": "http://127.0.0.1:18999/webhook",
                "message_title": "库存提醒",
                "message_template": "任务 {task_id} 命中：{summary}",
            },
        }
    )
    assert spec.alert.message_title == "库存提醒"
    assert spec.alert.message_template == "任务 {task_id} 命中：{summary}"
