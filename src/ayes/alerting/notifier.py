"""Minimal alert notifier for Ayes MVP."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Tuple
from urllib import error, request

from ayes.config.models import AlertConfig
from ayes.events.models import TimelineEvent


class WebhookNotifier:
    def send(self, *, event: TimelineEvent, alert_config: AlertConfig) -> Tuple[bool, str]:
        webhook_url = self._resolve_webhook_url(alert_config)
        if not webhook_url:
            return False, f"未配置 webhook 地址: {alert_config.webhook_url_env}"
        payload = {
            "msgtype": "text",
            "text": {
                "content": self._build_message(event),
            },
            "ayes_event": asdict(event),
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if 200 <= resp.status < 300:
                    return True, body or "ok"
                return False, f"HTTP {resp.status}: {body}"
        except error.URLError as exc:
            return False, str(exc)

    def _resolve_webhook_url(self, alert_config: AlertConfig) -> str:
        direct_url = (alert_config.webhook_url or "").strip()
        if direct_url:
            return direct_url
        return os.environ.get(alert_config.webhook_url_env, "").strip()

    def _build_message(self, event: TimelineEvent) -> str:
        process_name = event.target.process_name or "-"
        window_title = event.target.window_title or "-"
        return (
            "[Ayes] 命中监控目标\n\n"
            f"任务：{event.task_id}\n"
            f"时间：{int(event.timestamp)}\n"
            f"进程：{process_name}\n"
            f"窗口：{window_title}\n"
            f"优先级：{event.priority}\n"
            f"置信度：{event.confidence}\n\n"
            f"摘要：{event.summary}\n"
            f"事件：{event.event_id}"
        )
