"""In-memory structured log store."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Iterable, List, Optional
from uuid import uuid4

from ayes.logs.models import LogEntry


class LogStore:
    def __init__(self, *, retain_count: int = 500) -> None:
        self.retain_count = retain_count
        self._entries: List[LogEntry] = []

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
        entry = LogEntry(
            log_id=f"log_{uuid4().hex}",
            timestamp=timestamp or time.time(),
            category=category,
            level=level,
            message=message,
            task_id=task_id,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        if len(self._entries) > self.retain_count:
            self._entries = self._entries[-self.retain_count :]
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
