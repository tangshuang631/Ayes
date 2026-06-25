"""Task-scoped JSONL memory files for user-auditable retention."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ayes.events.models import TimelineEvent


def _safe_segment(value: str) -> str:
    text = str(value or "").strip() or "unknown"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)


def _date_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(float(timestamp), timezone.utc).date().isoformat()


class TaskMemoryFileStore:
    def __init__(self, *, runtime_dir: Path) -> None:
        self.runtime_dir = Path(runtime_dir).resolve()
        self.memory_root = self.runtime_dir / "memory"

    def task_dir(self, task_id: str) -> Path:
        return self.memory_root / _safe_segment(task_id)

    def short_event_path(self, *, task_id: str, timestamp: float) -> Path:
        safe_task_id = _safe_segment(task_id)
        date_text = _date_from_timestamp(timestamp)
        return self.task_dir(safe_task_id) / "short" / f"{date_text}-{safe_task_id}-details.jsonl"

    def long_summary_path(self, *, task_id: str, timestamp: float) -> Path:
        safe_task_id = _safe_segment(task_id)
        date_text = _date_from_timestamp(timestamp)
        return self.task_dir(safe_task_id) / "long" / f"{date_text}-{safe_task_id}-summary.jsonl"

    def append_short_event(self, event: TimelineEvent) -> Path:
        path = self.short_event_path(task_id=event.task_id, timestamp=event.timestamp)
        self._append_jsonl(path, asdict(event))
        return path

    def append_long_summary(self, payload: Dict[str, Any]) -> Path:
        task_id = str(payload.get("task_id") or "unknown")
        timestamp = float(payload.get("window_end") or payload.get("window_start") or 0.0)
        path = self.long_summary_path(task_id=task_id, timestamp=timestamp)
        self._append_jsonl(path, payload)
        return path

    def _append_jsonl(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            output.write("\n")
