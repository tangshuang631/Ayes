"""Helpers for creating testable watch spec files."""

from __future__ import annotations

import json
from pathlib import Path

from ayes.config.models import DEFAULT_SAMPLING_INTERVAL_MS


def build_window_observe_spec(*, window_id: int, output_path: str) -> str:
    payload = {
        "spec_version": "1.0",
        "mode": "observe",
        "target": {
            "type": "window",
            "window_id": window_id,
        },
        "sampling": {
            "screenshot_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
            "ocr_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
            "change_detection_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
            "max_fps": 2,
            "skip_ocr_when_no_change": False,
        },
        "memory": {
            "short_term": {
                "enabled": True,
                "retain_days": 7,
                "detail_level": "high",
            },
            "long_term": {
                "enabled": True,
                "retain_days": 14,
                "max_retain_hours": 720,
                "summary_interval_minutes": 5,
                "detail_level": "summary",
            },
            "disable_auto_cleanup": False,
        },
        "watch_intent": {
            "enabled": False,
        },
        "alert": {
            "enabled": False,
            "channel": "wecom_webhook",
            "webhook_url_env": "AYES_WECOM_WEBHOOK_URL",
            "priority_threshold": "medium",
            "cooldown_sec": 120,
            "dedupe_window_sec": 300,
        },
        "actions": {
            "refresh_click": {
                "enabled": False,
                "coordinate_space": "window",
                "interval_sec": 30,
                "cooldown_sec": 30,
                "max_clicks_per_hour": 120,
                "pause_when_target_matched": True,
            }
        },
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
