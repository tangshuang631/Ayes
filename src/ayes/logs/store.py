"""In-memory structured log store."""

from __future__ import annotations

import time
from dataclasses import asdict
import json
from typing import Iterable, List, Optional
from uuid import uuid4

from ayes.logs.models import LogEntry


class LogStore:
    def __init__(self, *, retain_count: int = 500, sink=None) -> None:
        self.retain_count = retain_count
        self._entries: List[LogEntry] = []
        self.sink = sink
        self._last_by_signature: dict[str, LogEntry] = {}

    def write(
        self,
        *,
        category: str,
        level: str,
        message: str,
        task_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        timestamp: Optional[float] = None,
    ) -> LogEntry:
        current_timestamp = timestamp or time.time()
        signature = self._signature(category=category, level=level, message=message, task_id=task_id, metadata=metadata or {})
        previous = self._last_by_signature.get(signature)
        if previous is not None and (current_timestamp - previous.timestamp) < 30.0:
            return previous
        entry = LogEntry(
            log_id=f"log_{uuid4().hex}",
            timestamp=current_timestamp,
            category=category,
            level=level,
            message=message,
            task_id=task_id,
            metadata=metadata or {},
        )
        self._last_by_signature[signature] = entry
        self._entries.append(entry)
        if len(self._entries) > self.retain_count:
            self._entries = self._entries[-self.retain_count :]
        if self.sink is not None:
            self.sink(entry)
        return entry

    def list_entries(self, *, category: Optional[str] = None, task_id: Optional[str] = None) -> List[LogEntry]:
        entries = self._entries
        if category:
            entries = [item for item in entries if item.category == category]
        if task_id:
            entries = [item for item in entries if item.task_id == task_id]
        return list(entries)

    def to_dicts(self, *, category: Optional[str] = None, task_id: Optional[str] = None) -> List[dict]:
        return [asdict(entry) for entry in self.list_entries(category=category, task_id=task_id)]

    def _signature(self, *, category: str, level: str, message: str, task_id: Optional[str], metadata: dict) -> str:
        return json.dumps(
            {
                "category": category,
                "level": level,
                "message": message,
                "task_id": task_id or "",
                "metadata": metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
