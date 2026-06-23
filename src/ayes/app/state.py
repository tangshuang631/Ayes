"""Shared application state for API and Web UI."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Optional

from ayes.app.runner import WatchRunner
from ayes.api.contracts import build_task_payload
from ayes.config.models import WatchSpec
from ayes.logs.store import LogStore
from ayes.memory.long_term import build_long_term_summary
from ayes.storage.sqlite_store import SQLiteStore
from ayes.targets.discovery.macos import MacOSWindowDiscovery


class AppState:
    def __init__(self) -> None:
        self.sqlite_store = SQLiteStore()
        self.log_store = LogStore(sink=self.sqlite_store.insert_log)
        self.window_discovery = MacOSWindowDiscovery()
        self.current_runner: Optional[WatchRunner] = None
        self.current_spec: Optional[WatchSpec] = None
        self.current_task_id: Optional[str] = None
        self.last_task_id: Optional[str] = None
        self.last_screenshot_path: Optional[str] = None
        self.log_store.write(category="system", level="info", message="Ayes AppState 初始化完成")

    def set_runner(self, spec: WatchSpec, task_id: str = "task_web") -> WatchRunner:
        self.current_spec = spec
        self.current_task_id = task_id
        self.last_task_id = task_id
        self.current_runner = WatchRunner(spec, task_id=task_id, event_sink=self.sqlite_store.insert_event)
        task_payload = build_task_payload(task_id=task_id, spec=spec)
        self.sqlite_store.upsert_task(
            task_id=task_payload["task_id"],
            mode=task_payload["mode"],
            target=task_payload["target"],
            spec=task_payload["spec"],
            created_at=task_payload["created_at"],
        )
        self.log_store.write(category="watch", level="info", message="监控任务已装载", task_id=task_id)
        return self.current_runner

    def clear_runner(self) -> None:
        if self.current_runner is not None and self.current_runner.events:
            summary = build_long_term_summary(task_id=self.current_task_id or "task_web", events=self.current_runner.events)
            self.sqlite_store.insert_long_term_summary(
                summary_id=summary["summary_id"],
                task_id=summary["task_id"],
                window_start=summary["window_start"],
                window_end=summary["window_end"],
                summary=summary["summary"],
                payload=summary,
            )
        self.current_runner = None
        self.current_spec = None
        self.current_task_id = None
        self.log_store.write(category="watch", level="info", message="监控任务已停止")

    def status(self) -> dict:
        return {
            "has_runner": self.current_runner is not None,
            "task_id": self.current_task_id,
            "last_task_id": self.last_task_id,
            "target": asdict(self.current_spec.target) if self.current_spec else None,
            "mode": self.current_spec.mode if self.current_spec else None,
            "event_count": len(self.current_runner.events) if self.current_runner else 0,
            "log_count": len(self.log_store.list_entries()),
            "last_screenshot_path": self.last_screenshot_path,
            "updated_at": time.time(),
        }
