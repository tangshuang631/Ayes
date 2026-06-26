"""SQLite persistence for tasks, events, memory, and logs."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from ayes.events.models import TimelineEvent
from ayes.logs.models import LogEntry
from ayes.app.paths import runtime_root
from ayes.app.task_paths import task_runtime_paths


class SQLiteStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or str(runtime_root() / "data" / "ayes.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cleanup_reminder_state (
                    state_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vision_enhancement_state (
                    state_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings_state (
                    state_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_memory_policies (
                    task_id TEXT PRIMARY KEY,
                    short_term_retain_days INTEGER NOT NULL,
                    long_term_retain_days INTEGER NOT NULL,
                    disable_auto_cleanup INTEGER NOT NULL,
                    memory_dir TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_roi_metadata (
                    roi_task_id TEXT PRIMARY KEY,
                    parent_task_id TEXT NOT NULL,
                    roi_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.commit()

    def _memory_dir_for_task(self, task_id: str) -> str:
        return str(task_runtime_paths(runtime_root(), task_id)["memory_dir"])

    def _default_task_memory_policy(self, task_id: str) -> Dict[str, Any]:
        return {
            "task_id": task_id,
            "short_term_retain_days": 7,
            "long_term_retain_days": 14,
            "disable_auto_cleanup": False,
            "memory_dir": self._memory_dir_for_task(task_id),
            "updated_at": None,
        }

    def upsert_task_memory_policy(
        self,
        *,
        task_id: str,
        short_term_retain_days: int,
        long_term_retain_days: int,
        disable_auto_cleanup: bool,
        updated_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        import time

        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise ValueError("task_id 不能为空")
        short_days = int(short_term_retain_days)
        long_days = int(long_term_retain_days)
        if short_days < 1 or short_days > 14:
            raise ValueError("short_term_retain_days 必须在 1 到 14 之间")
        if long_days < 1 or long_days > 30:
            raise ValueError("long_term_retain_days 必须在 1 到 30 之间")
        payload = {
            "task_id": normalized_task_id,
            "short_term_retain_days": short_days,
            "long_term_retain_days": long_days,
            "disable_auto_cleanup": bool(disable_auto_cleanup),
            "memory_dir": self._memory_dir_for_task(normalized_task_id),
            "updated_at": float(updated_at if updated_at is not None else time.time()),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO task_memory_policies
                (task_id, short_term_retain_days, long_term_retain_days, disable_auto_cleanup, memory_dir, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["task_id"],
                    payload["short_term_retain_days"],
                    payload["long_term_retain_days"],
                    1 if payload["disable_auto_cleanup"] else 0,
                    payload["memory_dir"],
                    payload["updated_at"],
                ),
            )
            connection.commit()
        return payload

    def get_task_memory_policy(self, task_id: str) -> Dict[str, Any]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise ValueError("task_id 不能为空")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT task_id, short_term_retain_days, long_term_retain_days, disable_auto_cleanup, memory_dir, updated_at
                FROM task_memory_policies
                WHERE task_id = ?
                """,
                (normalized_task_id,),
            ).fetchone()
        if row is None:
            return self._default_task_memory_policy(normalized_task_id)
        expected_memory_dir = self._memory_dir_for_task(normalized_task_id)
        stored_memory_dir = str(row[4] or "")
        if stored_memory_dir != expected_memory_dir:
            return self.upsert_task_memory_policy(
                task_id=normalized_task_id,
                short_term_retain_days=int(row[1]),
                long_term_retain_days=int(row[2]),
                disable_auto_cleanup=bool(row[3]),
                updated_at=row[5],
            )
        return {
            "task_id": row[0],
            "short_term_retain_days": int(row[1]),
            "long_term_retain_days": int(row[2]),
            "disable_auto_cleanup": bool(row[3]),
            "memory_dir": stored_memory_dir,
            "updated_at": row[5],
        }

    def upsert_app_settings(self, payload: Dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO app_settings_state (state_key, payload_json)
                VALUES (?, ?)
                """,
                ("app_settings", json.dumps(payload, ensure_ascii=False)),
            )
            connection.commit()

    def get_app_settings(self) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM app_settings_state WHERE state_key = ?",
                ("app_settings",),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

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

    def upsert_task_roi(
        self,
        *,
        roi_task_id: str,
        parent_task_id: str,
        roi_name: str,
        enabled: bool,
        created_at: float,
        updated_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        import time

        payload = {
            "roi_task_id": str(roi_task_id or "").strip(),
            "parent_task_id": str(parent_task_id or "").strip(),
            "roi_name": str(roi_name or "").strip(),
            "enabled": bool(enabled),
            "created_at": float(created_at),
            "updated_at": float(updated_at if updated_at is not None else time.time()),
        }
        if not payload["roi_task_id"] or not payload["parent_task_id"] or not payload["roi_name"]:
            raise ValueError("roi_task_id、parent_task_id、roi_name 不能为空")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO task_roi_metadata
                (roi_task_id, parent_task_id, roi_name, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["roi_task_id"],
                    payload["parent_task_id"],
                    payload["roi_name"],
                    1 if payload["enabled"] else 0,
                    payload["created_at"],
                    payload["updated_at"],
                ),
            )
            connection.commit()
        return payload

    def get_task_roi(self, roi_task_id: str) -> Optional[Dict[str, Any]]:
        normalized = str(roi_task_id or "").strip()
        if not normalized:
            raise ValueError("roi_task_id 不能为空")
        if "__roi_" not in normalized:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT roi_task_id, parent_task_id, roi_name, enabled, created_at, updated_at
                FROM task_roi_metadata
                WHERE roi_task_id = ?
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        if str(row[1] or "").strip() == normalized:
            return None
        return {
            "roi_task_id": row[0],
            "parent_task_id": row[1],
            "roi_name": row[2],
            "enabled": bool(row[3]),
            "created_at": row[4],
            "updated_at": row[5],
        }

    def list_task_rois(self, parent_task_id: str) -> List[Dict[str, Any]]:
        normalized = str(parent_task_id or "").strip()
        if not normalized:
            raise ValueError("parent_task_id 不能为空")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT roi_task_id, parent_task_id, roi_name, enabled, created_at, updated_at
                FROM task_roi_metadata
                WHERE parent_task_id = ?
                ORDER BY created_at ASC
                """,
                (normalized,),
            ).fetchall()
        return [
            {
                "roi_task_id": row[0],
                "parent_task_id": row[1],
                "roi_name": row[2],
                "enabled": bool(row[3]),
                "created_at": row[4],
                "updated_at": row[5],
            }
            for row in rows
        ]

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

    def summarize_logs(
        self,
        *,
        task_id: Optional[str] = None,
        category: Optional[str] = None,
        since_timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        query = """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN lower(level) = 'error' THEN 1 ELSE 0 END) AS error_count,
                SUM(CASE WHEN lower(level) IN ('warn', 'warning') THEN 1 ELSE 0 END) AS warn_count,
                MAX(timestamp) AS latest_timestamp
            FROM logs
        """
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
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return {
            "count": int(row[0] or 0),
            "error_count": int(row[1] or 0),
            "warn_count": int(row[2] or 0),
            "latest_timestamp": row[3],
        }

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

    def list_tasks(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id, mode, target_json, spec_json, created_at
                FROM watch_tasks
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "task_id": row[0],
                "mode": row[1],
                "target": json.loads(row[2]),
                "spec": json.loads(row[3]),
                "created_at": row[4],
            }
            for row in rows
        ]

    def delete_task_data(self, task_id: str) -> Dict[str, int]:
        deleted = {"tasks": 0, "events": 0, "logs": 0, "long_term_summaries": 0, "task_memory_policies": 0, "task_roi_metadata": 0}
        with self._connect() as connection:
            deleted["events"] = int(
                (connection.execute("DELETE FROM events WHERE task_id = ?", (task_id,)).rowcount or 0)
            )
            deleted["logs"] = int(
                (connection.execute("DELETE FROM logs WHERE task_id = ?", (task_id,)).rowcount or 0)
            )
            deleted["long_term_summaries"] = int(
                (connection.execute("DELETE FROM long_term_summaries WHERE task_id = ?", (task_id,)).rowcount or 0)
            )
            deleted["tasks"] = int(
                (connection.execute("DELETE FROM watch_tasks WHERE task_id = ?", (task_id,)).rowcount or 0)
            )
            deleted["task_memory_policies"] = int(
                (connection.execute("DELETE FROM task_memory_policies WHERE task_id = ?", (task_id,)).rowcount or 0)
            )
            deleted["task_roi_metadata"] = int(
                (connection.execute("DELETE FROM task_roi_metadata WHERE roi_task_id = ? OR parent_task_id = ?", (task_id, task_id)).rowcount or 0)
            )
            connection.commit()
        return deleted

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

    def delete_events_before(self, *, task_id: str, cutoff_timestamp: float) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM events
                WHERE task_id = ? AND timestamp < ?
                """,
                (task_id, cutoff_timestamp),
            )
            connection.commit()
            return int(cursor.rowcount or 0)

    def upsert_cleanup_reminder(
        self,
        *,
        enabled: bool,
        last_prompt_at: Optional[float],
        snoozed_until: Optional[float],
        suppress_forever: bool,
        data_dir: str,
        next_check_after_days: int,
    ) -> None:
        payload = {
            "enabled": enabled,
            "last_prompt_at": last_prompt_at,
            "snoozed_until": snoozed_until,
            "suppress_forever": suppress_forever,
            "data_dir": data_dir,
            "next_check_after_days": next_check_after_days,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO cleanup_reminder_state (state_key, payload_json)
                VALUES (?, ?)
                """,
                ("cleanup_reminder", json.dumps(payload, ensure_ascii=False)),
            )
            connection.commit()

    def get_cleanup_reminder(self) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM cleanup_reminder_state WHERE state_key = ?",
                ("cleanup_reminder",),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def upsert_vision_enhancement_settings(
        self,
        *,
        enabled: bool,
        provider: str,
        model: str,
        auto_use_when_available: bool,
    ) -> None:
        payload = {
            "enabled": enabled,
            "provider": provider,
            "model": model,
            "auto_use_when_available": auto_use_when_available,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO vision_enhancement_state (state_key, payload_json)
                VALUES (?, ?)
                """,
                ("vision_enhancement", json.dumps(payload, ensure_ascii=False)),
            )
            connection.commit()

    def get_vision_enhancement_settings(self) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM vision_enhancement_state WHERE state_key = ?",
                ("vision_enhancement",),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])
