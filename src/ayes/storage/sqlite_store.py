"""SQLite persistence for tasks, events, memory, and logs."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from ayes.events.models import TimelineEvent
from ayes.logs.models import LogEntry


class SQLiteStore:
    def __init__(self, db_path: str = "data/ayes.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS watch_tasks (
                    task_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    target_json TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS logs (
                    log_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    timestamp REAL NOT NULL,
                    category TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_summaries (
                    summary_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    window_start REAL NOT NULL,
                    window_end REAL NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def upsert_task(self, *, task_id: str, mode: str, target: dict, spec: dict, created_at: float) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO watch_tasks (task_id, mode, target_json, spec_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                  mode=excluded.mode,
                  target_json=excluded.target_json,
                  spec_json=excluded.spec_json
                """,
                (task_id, mode, json.dumps(target, ensure_ascii=False), json.dumps(spec, ensure_ascii=False), created_at),
            )
            connection.commit()

    def insert_event(self, event: TimelineEvent) -> None:
        payload = asdict(event)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO events (event_id, task_id, timestamp, event_type, priority, summary, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    event.timestamp,
                    event.event_type,
                    event.priority,
                    event.summary,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            connection.commit()

    def insert_log(self, entry: LogEntry) -> None:
        payload = asdict(entry)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO logs (log_id, task_id, timestamp, category, level, message, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.log_id,
                    entry.task_id,
                    entry.timestamp,
                    entry.category,
                    entry.level,
                    entry.message,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            connection.commit()

    def list_events(
        self,
        *,
        task_id: Optional[str] = None,
        source: Optional[str] = None,
        since_timestamp: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = "SELECT payload_json FROM events"
        params: list[Any] = []
        conditions: list[str] = []
        if task_id:
            conditions.append("task_id = ?")
            params.append(task_id)
        if source:
            conditions.append("json_extract(payload_json, '$.source') = ?")
            params.append(source)
        if since_timestamp is not None:
            conditions.append("timestamp >= ?")
            params.append(since_timestamp)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_logs(
        self,
        *,
        task_id: Optional[str] = None,
        category: Optional[str] = None,
        since_timestamp: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = "SELECT payload_json FROM logs"
        params: list[Any] = []
        conditions: list[str] = []
        if task_id:
            conditions.append("task_id = ?")
            params.append(task_id)
        if category:
            conditions.append("category = ?")
            params.append(category)
        if since_timestamp is not None:
            conditions.append("timestamp >= ?")
            params.append(since_timestamp)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row[0]) for row in rows]

    def query_events(
        self,
        *,
        task_id: str,
        minutes: int,
        keyword: Optional[str] = None,
        now: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        import time

        current_now = now if now is not None else time.time()
        since_timestamp = current_now - (minutes * 60)
        items = self.list_events(task_id=task_id, since_timestamp=since_timestamp, limit=limit)
        if not keyword:
            return list(reversed(items))
        lowered = keyword.lower()
        matched = []
        for item in reversed(items):
            text = item.get("text") or {}
            tags = item.get("tags") or []
            if (
                lowered in (item.get("summary") or "").lower()
                or lowered in (text.get("ocr_text") or "").lower()
                or lowered in (text.get("normalized_text") or "").lower()
                or any(lowered in str(tag).lower() for tag in tags)
            ):
                matched.append(item)
        return matched

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT task_id, mode, target_json, spec_json, created_at FROM watch_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0],
            "mode": row[1],
            "target": json.loads(row[2]),
            "spec": json.loads(row[3]),
            "created_at": row[4],
        }

    def insert_long_term_summary(
        self,
        *,
        summary_id: str,
        task_id: str,
        window_start: float,
        window_end: float,
        summary: str,
        payload: Dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO long_term_summaries
                (summary_id, task_id, window_start, window_end, summary, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    summary_id,
                    task_id,
                    window_start,
                    window_end,
                    summary,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            connection.commit()

    def list_long_term_summaries(self, *, task_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        query = "SELECT payload_json FROM long_term_summaries"
        params: list[Any] = []
        if task_id:
            query += " WHERE task_id = ?"
            params.append(task_id)
        query += " ORDER BY window_end DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row[0]) for row in rows]

    def query_long_term_summaries(
        self,
        *,
        task_id: str,
        hours: int,
        keyword: Optional[str] = None,
        now: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        import time

        current_now = now if now is not None else time.time()
        since_timestamp = current_now - (hours * 60 * 60)
        query = "SELECT payload_json FROM long_term_summaries WHERE task_id = ? AND window_end >= ? ORDER BY window_end DESC LIMIT ?"
        params: list[Any] = [task_id, since_timestamp, limit]
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        items = [json.loads(row[0]) for row in rows]
        if not keyword:
            return list(reversed(items))
        lowered = keyword.lower()
        matched: List[Dict[str, Any]] = []
        for item in reversed(items):
            haystacks = [
                str(item.get("summary") or ""),
                " ".join(str(event_id) for event_id in (item.get("event_ids") or [])),
            ]
            if any(lowered in haystack.lower() for haystack in haystacks):
                matched.append(item)
        return matched

    def delete_long_term_summaries_before(self, *, task_id: str, cutoff_timestamp: float) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM long_term_summaries
                WHERE task_id = ? AND window_end < ?
                """,
                (task_id, cutoff_timestamp),
            )
            connection.commit()
            return int(cursor.rowcount or 0)
