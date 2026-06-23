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
