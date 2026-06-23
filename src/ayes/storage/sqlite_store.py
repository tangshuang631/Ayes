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

    def list_events(self, *, task_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT payload_json FROM events"
        params: list[Any] = []
        if task_id:
            query += " WHERE task_id = ?"
            params.append(task_id)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_logs(self, *, task_id: Optional[str] = None, category: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT payload_json FROM logs WHERE 1=1"
        params: list[Any] = []
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row[0]) for row in rows]

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
