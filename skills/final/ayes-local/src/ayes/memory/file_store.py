"""Task-scoped JSONL memory files for user-auditable retention."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ayes.events.models import TimelineEvent
from ayes.app.task_paths import date_from_timestamp, safe_task_segment, task_runtime_paths


class TaskMemoryFileStore:
    def __init__(self, *, runtime_dir: Path, task_path_resolver=None) -> None:
        self.runtime_dir = Path(runtime_dir).resolve()
        self.task_path_resolver = task_path_resolver

    def task_dir(self, task_id: str, *, timestamp: float | None = None) -> Path:
        if self.task_path_resolver is not None:
            paths = self.task_path_resolver(task_id, timestamp=timestamp)
            return Path(paths["memory_dir"])
        return task_runtime_paths(self.runtime_dir, task_id, timestamp=timestamp)["memory_dir"]

    def short_event_path(self, *, task_id: str, timestamp: float) -> Path:
        safe_task_id = safe_task_segment(task_id)
        date_text = date_from_timestamp(timestamp)
        return self.task_dir(safe_task_id, timestamp=timestamp) / "short" / f"{date_text}-{safe_task_id}-details.jsonl"

    def long_summary_path(self, *, task_id: str, timestamp: float) -> Path:
        safe_task_id = safe_task_segment(task_id)
        date_text = date_from_timestamp(timestamp)
        return self.task_dir(safe_task_id, timestamp=timestamp) / "long" / f"{date_text}-{safe_task_id}-summary.jsonl"

    def append_short_event(self, event: TimelineEvent) -> Path:
        path = self.short_event_path(task_id=event.task_id, timestamp=event.timestamp)
        payload = self._compact_short_event(event)
        if payload is not None:
            self._append_jsonl(path, payload)
        return path

    def append_long_summary(self, payload: Dict[str, Any]) -> Path:
        task_id = str(payload.get("task_id") or "unknown")
        timestamp = float(payload.get("window_end") or payload.get("window_start") or 0.0)
        path = self.long_summary_path(task_id=task_id, timestamp=timestamp)
        self._append_jsonl(path, self._compact_long_summary(payload))
        return path

    def _append_jsonl(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            output.write("\n")

    def delete_expired_files(self, *, task_id: str, short_cutoff: float, long_cutoff: float) -> Dict[str, int]:
        safe_task_id = safe_task_segment(task_id)
        root = self.runtime_dir / "tasks"
        deleted_short = self._delete_expired_paths(
            root=root,
            safe_task_id=safe_task_id,
            memory_kind="short",
            suffix="-details.jsonl",
            cutoff_timestamp=short_cutoff,
        )
        deleted_long = self._delete_expired_paths(
            root=root,
            safe_task_id=safe_task_id,
            memory_kind="long",
            suffix="-summary.jsonl",
            cutoff_timestamp=long_cutoff,
        )
        return {"deleted_short_files": deleted_short, "deleted_long_files": deleted_long}

    def _delete_expired_paths(self, *, root: Path, safe_task_id: str, memory_kind: str, suffix: str, cutoff_timestamp: float) -> int:
        deleted = 0
        for path in root.glob(f"**/{safe_task_id}/memory/{memory_kind}/*{suffix}"):
            if not path.is_file():
                continue
            date_text = path.name.split("-", 3)
            try:
                file_date = "-".join(date_text[:3])
                file_timestamp = datetime.fromisoformat(file_date).replace(tzinfo=timezone.utc).timestamp()
            except Exception:
                file_timestamp = path.stat().st_mtime
            if file_timestamp >= cutoff_timestamp:
                continue
            try:
                path.unlink()
                deleted += 1
            except OSError:
                pass
        return deleted

    def _compact_short_event(self, event: TimelineEvent) -> Optional[Dict[str, Any]]:
        if event.event_type in {"vision_skipped", "vision_triggered"}:
            return None
        info = self._best_event_info(event)
        if not info:
            return None
        return {
            "time": self._format_timestamp(event.timestamp),
            "info": info,
        }

    def _compact_long_summary(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "from": self._format_timestamp(float(payload.get("window_start") or 0.0)),
            "to": self._format_timestamp(float(payload.get("window_end") or payload.get("window_start") or 0.0)),
            "info": self._trim_info(self._clean_long_info(str(payload.get("summary") or "").strip()) or "该时间段内无高价值摘要"),
        }

    def _best_event_info(self, event: TimelineEvent) -> str:
        summary = str(event.summary or "").strip()
        text = str(event.text.ocr_text or event.text.normalized_text or "").strip()
        visual_summary = str(event.visual.summary or "").strip()
        for value in [summary, text, visual_summary]:
            if not value:
                continue
            if value.startswith("OCR vision |") or value.startswith("视觉增强已跳过") or value.startswith("视觉增强已触发"):
                continue
            return self._trim_info(value)
        return ""

    def _trim_info(self, value: str) -> str:
        text = " ".join(str(value or "").split())
        if len(text) > 180:
            return text[:177] + "..."
        return text

    def _clean_long_info(self, value: str) -> str:
        parts = []
        for raw in str(value or "").split("；"):
            part = self._trim_info(raw)
            if not part:
                continue
            if part.startswith("视觉增强已跳过") or part.startswith("视觉增强已触发") or part.startswith("OCR vision |"):
                continue
            if part not in parts:
                parts.append(part)
        return "；".join(parts)

    def _format_timestamp(self, timestamp: float) -> str:
        return datetime.fromtimestamp(float(timestamp), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
