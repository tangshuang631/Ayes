"""Compact task memory index for token-efficient agent queries."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Dict, List, Optional

from ayes.app.task_paths import date_from_timestamp, safe_task_segment, task_runtime_paths
from ayes.events.models import TimelineEvent
from ayes.memory.content_signal import clean_memory_summary
from ayes.memory.facts import MemoryFact, MemoryFactExtractor


class MemorySearchIndex:
    def __init__(self, *, runtime_dir: Path, task_path_resolver=None) -> None:
        self.runtime_dir = Path(runtime_dir).resolve()
        self.task_path_resolver = task_path_resolver
        self.fact_extractor = MemoryFactExtractor()

    def task_index_dir(self, task_id: str, *, timestamp: float | None = None) -> Path:
        if self.task_path_resolver is not None:
            paths = self.task_path_resolver(task_id, timestamp=timestamp)
            return Path(paths["task_dir"]) / "index"
        return task_runtime_paths(self.runtime_dir, task_id, timestamp=timestamp)["task_dir"] / "index"

    def index_event(self, event: TimelineEvent) -> Optional[dict]:
        fact = self.fact_extractor.extract(event)
        chunk = fact.to_index_chunk() if fact is not None else None
        if chunk is None:
            return None
        self.index_chunk(chunk)
        return chunk

    def index_fact(self, fact: MemoryFact) -> Optional[dict]:
        chunk = fact.to_index_chunk()
        self.index_chunk(chunk)
        return chunk

    def index_long_summary(self, payload: Dict[str, Any]) -> Optional[dict]:
        task_id = str(payload.get("task_id") or "").strip()
        info = clean_memory_summary(str(payload.get("summary") or ""))
        if not task_id or not info:
            return None
        timestamp = float(payload.get("window_end") or payload.get("window_start") or 0.0)
        chunk = {
            "chunk_id": str(payload.get("summary_id") or f"long:{task_id}:{int(timestamp)}"),
            "task_id": task_id,
            "timestamp": timestamp,
            "layer": "long",
            "source": "long_term",
            "event_type": "long_term_summary",
            "info": self._trim(info, 240),
            "code": "",
            "region": "",
            "target": "",
            "tags": ["long_term"],
            "confidence": 0.78,
        }
        self.index_chunk(chunk)
        return chunk

    def index_chunk(self, chunk: Dict[str, Any]) -> None:
        task_id = str(chunk.get("task_id") or "").strip()
        timestamp = float(chunk.get("timestamp") or 0.0)
        if not task_id:
            return
        normalized = self._normalize_chunk(chunk)
        index_dir = self.task_index_dir(task_id, timestamp=timestamp)
        index_dir.mkdir(parents=True, exist_ok=True)
        self._append_chunk_file(index_dir=index_dir, chunk=normalized)
        self._upsert_fts(index_dir=index_dir, chunk=normalized)

    def query(
        self,
        *,
        task_id: str,
        question: str,
        minutes: int = 240,
        now: float | None = None,
        limit: int = 8,
        compact_items: bool = False,
    ) -> Dict[str, Any]:
        current_now = now if now is not None else datetime.now(timezone.utc).timestamp()
        since_timestamp = current_now - (minutes * 60)
        index_dirs = self._candidate_index_dirs(task_id=task_id, since_timestamp=since_timestamp, now=current_now)
        candidates: list[dict] = []
        query_limit = self._candidate_limit(question=question, limit=limit)
        for index_dir in index_dirs:
            candidates.extend(self._query_index_dir(index_dir=index_dir, task_id=task_id, question=question, since_timestamp=since_timestamp, limit=query_limit))
        backfilled = False
        if not candidates:
            backfilled = self.backfill_from_memory_files(task_id=task_id, since_timestamp=since_timestamp)
            if backfilled:
                index_dirs = self._candidate_index_dirs(task_id=task_id, since_timestamp=since_timestamp, now=current_now)
                for index_dir in index_dirs:
                    candidates.extend(self._query_index_dir(index_dir=index_dir, task_id=task_id, question=question, since_timestamp=since_timestamp, limit=query_limit))
        if not candidates:
            candidates = self._query_chunk_files(task_id=task_id, since_timestamp=since_timestamp)
        ranked = self._rank_candidates(candidates, question=question, since_timestamp=since_timestamp)[:limit]
        if _is_content_identity_question(question):
            ranked = self._prefer_title_facts(ranked)
        if not _is_content_identity_question(question) and not _question_prefers_alert_or_status(question):
            ranked = sorted(ranked, key=lambda item: float(item.get("timestamp") or 0.0))
        return_items = [self._compact_query_item(item) for item in ranked] if compact_items else ranked
        return {
            "task_id": task_id,
            "question": question,
            "minutes": minutes,
            "answer": self._build_answer(ranked, minutes=minutes),
            "items": return_items,
            "count": len(ranked),
            "retrieval": {
                "strategy": "fts_chunk_rerank",
                "index_dirs": [str(path) for path in index_dirs],
                "candidate_count": len(candidates),
                "returned_count": len(ranked),
                "backfilled": backfilled,
                "token_saving": "compact_chunks_only",
            },
            "needs_detail": len(ranked) == 0,
            "next_step": "screenshot_or_observe_live_only_if_user_needs_visual_evidence" if ranked else "broaden_time_or_check_long_term",
        }

    def backfill_from_memory_files(self, *, task_id: str, since_timestamp: float = 0.0) -> bool:
        chunks = self._chunks_from_memory_files(task_id=task_id, since_timestamp=since_timestamp)
        for chunk in chunks:
            self.index_chunk(chunk)
        return bool(chunks)

    def delete_task_index(self, task_id: str) -> Dict[str, Any]:
        index_dirs = self._existing_task_index_dirs(task_id)
        deleted_bytes = 0
        deleted_paths = 0
        errors = []
        paths = []
        for index_dir in index_dirs:
            size = self._path_size(index_dir)
            try:
                shutil.rmtree(index_dir)
                deleted_bytes += size
                deleted_paths += 1
                paths.append(str(index_dir))
            except OSError as exc:
                errors.append({"path": str(index_dir), "error": str(exc)})
        return {
            "task_id": task_id,
            "deleted": deleted_paths > 0,
            "deleted_bytes": deleted_bytes,
            "deleted_paths": deleted_paths,
            "paths": paths,
            "errors": errors,
        }

    def rebuild_task_index(self, task_id: str, *, since_timestamp: float = 0.0) -> Dict[str, Any]:
        self.delete_task_index(task_id)
        chunks = self._chunks_from_memory_files(task_id=task_id, since_timestamp=since_timestamp)
        for chunk in chunks:
            self.index_chunk(chunk)
        return {
            "task_id": task_id,
            "indexed_chunks": len(chunks),
            "since_timestamp": since_timestamp,
            "index_dirs": [str(path) for path in self._existing_task_index_dirs(task_id)],
        }

    def _chunk_from_event(self, event: TimelineEvent) -> Optional[dict]:
        if event.event_type in {"vision_skipped", "vision_triggered"}:
            return None
        if self._is_no_change_chunk({"source": event.source, "event_type": event.event_type, "info": event.summary}):
            return None
        payload = asdict(event)
        info = self._best_info(payload)
        if not info:
            return None
        return {
            "chunk_id": event.event_id,
            "task_id": event.task_id,
            "timestamp": event.timestamp,
            "layer": "short",
            "source": event.source,
            "event_type": event.event_type,
            "info": self._trim(info, 220),
            "code": "",
            "region": ((payload.get("region") or {}).get("name") or (payload.get("region") or {}).get("region_id") or ""),
            "target": self._target_label(payload.get("target") or {}),
            "tags": list(payload.get("tags") or []),
            "confidence": float(payload.get("confidence") or 0.0),
        }

    def _best_info(self, event: Dict[str, Any]) -> str:
        text = event.get("text") or {}
        visual = event.get("visual") or {}
        for value in [
            event.get("summary"),
            text.get("normalized_text"),
            text.get("ocr_text"),
            visual.get("summary"),
        ]:
            cleaned = clean_memory_summary(str(value or ""))
            if not cleaned:
                continue
            if cleaned.startswith(("OCR vision |", "视觉增强已跳过", "视觉增强已触发")):
                continue
            return cleaned
        return ""

    def _normalize_chunk(self, chunk: Dict[str, Any]) -> dict:
        timestamp = float(chunk.get("timestamp") or 0.0)
        code = clean_memory_summary(str(chunk.get("code") or ""))
        code_fields = _parse_code_fields(code)
        return {
            "chunk_id": str(chunk.get("chunk_id") or f"chunk:{int(timestamp)}"),
            "task_id": str(chunk.get("task_id") or ""),
            "timestamp": timestamp,
            "time": self._format_timestamp(timestamp),
            "layer": str(chunk.get("layer") or "short"),
            "source": str(chunk.get("source") or ""),
            "event_type": str(chunk.get("event_type") or ""),
            "info": self._trim(clean_memory_summary(str(chunk.get("info") or "")), 240),
            "code": code,
            "scene": clean_memory_summary(str(chunk.get("scene") or code_fields["scene"] or "")),
            "region_slot": clean_memory_summary(str(chunk.get("region_slot") or code_fields["region_slot"] or "")),
            "k1": clean_memory_summary(str(chunk.get("k1") or code_fields["k1"] or "")),
            "k2": clean_memory_summary(str(chunk.get("k2") or code_fields["k2"] or "")),
            "k3": clean_memory_summary(str(chunk.get("k3") or code_fields["k3"] or "")),
            "pos": clean_memory_summary(str(chunk.get("pos") or code_fields["pos"] or "")),
            "sub": clean_memory_summary(str(chunk.get("sub") or code_fields["sub"] or "")),
            "subj": clean_memory_summary(str(chunk.get("subj") or code_fields["subj"] or "")),
            "ctx": clean_memory_summary(str(chunk.get("ctx") or code_fields["ctx"] or "")),
            "bg": clean_memory_summary(str(chunk.get("bg") or code_fields["bg"] or "")),
            "region": clean_memory_summary(str(chunk.get("region") or "")),
            "target": clean_memory_summary(str(chunk.get("target") or "")),
            "tags": [str(tag) for tag in (chunk.get("tags") or [])][:8],
            "confidence": float(chunk.get("confidence") or 0.0),
        }

    def _append_chunk_file(self, *, index_dir: Path, chunk: Dict[str, Any]) -> None:
        chunk_dir = index_dir / "chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        timestamp = float(chunk.get("timestamp") or 0.0)
        date_hour = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d-%H")
        path = chunk_dir / f"{date_hour}.jsonl"
        if self._chunk_file_contains_id(path=path, chunk_id=str(chunk.get("chunk_id") or "")):
            return
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(chunk, ensure_ascii=False, sort_keys=True))
            output.write("\n")

    def _chunk_file_contains_id(self, *, path: Path, chunk_id: str) -> bool:
        if not chunk_id or not path.exists():
            return False
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(payload.get("chunk_id") or "") == chunk_id:
                        return True
        except OSError:
            return False
        return False

    def _upsert_fts(self, *, index_dir: Path, chunk: Dict[str, Any]) -> None:
        db_path = index_dir / "fts.sqlite"
        with sqlite3.connect(str(db_path)) as connection:
            self._initialize_schema(connection)
            connection.execute(
                """
                INSERT OR REPLACE INTO memory_chunks
                (chunk_id, task_id, timestamp, layer, source, event_type, info, code, scene, region_slot, k1, k2, k3, pos, sub, subj, ctx, bg, region, target, tags_json, confidence, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk["chunk_id"],
                    chunk["task_id"],
                    chunk["timestamp"],
                    chunk["layer"],
                    chunk["source"],
                    chunk["event_type"],
                    chunk["info"],
                    chunk["code"],
                    chunk["scene"],
                    chunk["region_slot"],
                    chunk["k1"],
                    chunk["k2"],
                    chunk["k3"],
                    chunk["pos"],
                    chunk["sub"],
                    chunk["subj"],
                    chunk["ctx"],
                    chunk["bg"],
                    chunk["region"],
                    chunk["target"],
                    json.dumps(chunk["tags"], ensure_ascii=False),
                    chunk["confidence"],
                    json.dumps(chunk, ensure_ascii=False),
                ),
            )
            try:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO memory_chunks_fts
                    (chunk_id, task_id, info, scene, region_slot, k1, k2, k3, pos, sub, subj, ctx, bg, region, target, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["chunk_id"],
                        chunk["task_id"],
                        chunk["info"],
                        chunk["scene"],
                        chunk["region_slot"],
                        chunk["k1"],
                        chunk["k2"],
                        chunk["k3"],
                        chunk["pos"],
                        chunk["sub"],
                        chunk["subj"],
                        chunk["ctx"],
                        chunk["bg"],
                        chunk["region"],
                        chunk["target"],
                        " ".join(chunk["tags"]),
                    ),
                )
            except sqlite3.OperationalError:
                pass
            connection.commit()

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_chunks (
                chunk_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                layer TEXT NOT NULL,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                info TEXT NOT NULL,
                code TEXT NOT NULL,
                scene TEXT NOT NULL,
                region_slot TEXT NOT NULL,
                k1 TEXT NOT NULL,
                k2 TEXT NOT NULL,
                k3 TEXT NOT NULL,
                pos TEXT NOT NULL,
                sub TEXT NOT NULL,
                subj TEXT NOT NULL,
                ctx TEXT NOT NULL,
                bg TEXT NOT NULL,
                region TEXT NOT NULL,
                target TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts
                USING fts5(chunk_id UNINDEXED, task_id UNINDEXED, info, scene, region_slot, k1, k2, k3, pos, sub, subj, ctx, bg, region, target, tags)
                """
            )
        except sqlite3.OperationalError:
            pass
        try:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(memory_chunks)").fetchall()]
            for name in ["code", "scene", "region_slot", "k1", "k2", "k3", "pos", "sub", "subj", "ctx", "bg"]:
                if name not in columns:
                    connection.execute(f"ALTER TABLE memory_chunks ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass

    def _query_index_dir(self, *, index_dir: Path, task_id: str, question: str, since_timestamp: float, limit: int) -> list[dict]:
        db_path = index_dir / "fts.sqlite"
        if not db_path.exists():
            return []
        terms = self._query_terms(question)
        with sqlite3.connect(str(db_path)) as connection:
            if terms:
                fts_query = " OR ".join(terms)
                try:
                    rows = connection.execute(
                        """
                        SELECT c.payload_json
                        FROM memory_chunks_fts f
                        JOIN memory_chunks c ON c.chunk_id = f.chunk_id
                        WHERE f.task_id = ? AND c.timestamp >= ? AND memory_chunks_fts MATCH ?
                        ORDER BY c.timestamp DESC
                        LIMIT ?
                        """,
                        (task_id, since_timestamp, fts_query, limit),
                    ).fetchall()
                    if rows:
                        return [self._normalize_chunk(json.loads(row[0])) for row in rows]
                except sqlite3.OperationalError:
                    pass
            rows = connection.execute(
                """
                SELECT payload_json FROM memory_chunks
                WHERE task_id = ? AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (task_id, since_timestamp, limit),
            ).fetchall()
        return [self._normalize_chunk(json.loads(row[0])) for row in rows]

    def _query_chunk_files(self, *, task_id: str, since_timestamp: float) -> list[dict]:
        chunks: list[dict] = []
        root = self.runtime_dir / "tasks"
        for path in root.glob(f"**/{safe_task_segment(task_id)}/index/chunks/*.jsonl"):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if float(payload.get("timestamp") or 0.0) >= since_timestamp:
                    chunks.append(self._normalize_chunk(payload))
        return chunks

    def _existing_task_index_dirs(self, task_id: str) -> list[Path]:
        root = self.runtime_dir / "tasks"
        if not root.exists():
            return []
        safe_task_id = safe_task_segment(task_id)
        return sorted(path for path in root.glob(f"**/{safe_task_id}/index") if path.exists())

    def _path_size(self, path: Path) -> int:
        try:
            if path.is_file():
                return path.stat().st_size
            if not path.exists():
                return 0
            return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
        except OSError:
            return 0

    def _chunks_from_memory_files(self, *, task_id: str, since_timestamp: float) -> list[dict]:
        chunks: list[dict] = []
        root = self.runtime_dir / "tasks"
        safe_task_id = safe_task_segment(task_id)
        for path in root.glob(f"**/{safe_task_id}/memory/compact/*.jsonl"):
            chunks.extend(self._chunks_from_compact_file(path=path, task_id=task_id, since_timestamp=since_timestamp))
        for path in root.glob(f"**/{safe_task_id}/memory/short/*.jsonl"):
            chunks.extend(self._chunks_from_short_file(path=path, task_id=task_id, since_timestamp=since_timestamp))
        for path in root.glob(f"**/{safe_task_id}/memory/long/*.jsonl"):
            chunks.extend(self._chunks_from_long_file(path=path, task_id=task_id, since_timestamp=since_timestamp))
        return chunks

    def _chunks_from_compact_file(self, *, path: Path, task_id: str, since_timestamp: float) -> list[dict]:
        chunks = []
        for index, payload in enumerate(self._read_jsonl(path)):
            timestamp = _parse_memory_time(payload.get("to") or payload.get("from"))
            if timestamp < since_timestamp:
                continue
            info = clean_memory_summary(str(payload.get("info") or ""))
            if not info:
                continue
            repeat_count = int(payload.get("repeat_count") or 1)
            if repeat_count > 1:
                info = f"{info}（持续重复 {repeat_count} 次）"
            chunks.append(
                {
                    "chunk_id": f"compact:{path.name}:{index}",
                    "task_id": task_id,
                    "timestamp": timestamp,
                    "layer": "compact",
                    "source": "file_memory_compact",
                    "event_type": "compact_memory_segment",
                    "info": info,
                    "code": clean_memory_summary(str(payload.get("code") or "")),
                    "region": clean_memory_summary(str(payload.get("region") or "")),
                    "target": "",
                    "tags": ["compact_memory"],
                    "confidence": 0.86,
                }
            )
        return chunks

    def _chunks_from_short_file(self, *, path: Path, task_id: str, since_timestamp: float) -> list[dict]:
        chunks = []
        for index, payload in enumerate(self._read_jsonl(path)):
            timestamp = _parse_memory_time(payload.get("time"))
            if timestamp < since_timestamp:
                continue
            info = clean_memory_summary(str(payload.get("info") or ""))
            if not info or _is_empty_long_summary_placeholder(info):
                continue
            chunks.append(
                {
                    "chunk_id": f"short:{path.name}:{index}",
                    "task_id": task_id,
                    "timestamp": timestamp,
                    "layer": "short",
                    "source": "file_memory",
                    "event_type": "compact_short_memory",
                    "info": info,
                    "code": clean_memory_summary(str(payload.get("code") or "")),
                    "region": clean_memory_summary(str(payload.get("region") or "")),
                    "target": clean_memory_summary(str(payload.get("target") or "")),
                    "tags": ["short_memory"],
                    "confidence": 0.84,
                }
            )
        return chunks

    def _chunks_from_long_file(self, *, path: Path, task_id: str, since_timestamp: float) -> list[dict]:
        chunks = []
        for index, payload in enumerate(self._read_jsonl(path)):
            timestamp = _parse_memory_time(payload.get("to") or payload.get("from"))
            if timestamp < since_timestamp:
                continue
            info = clean_memory_summary(str(payload.get("info") or ""))
            if not info:
                continue
            chunks.append(
                {
                    "chunk_id": f"long:{path.name}:{index}",
                    "task_id": task_id,
                    "timestamp": timestamp,
                    "layer": "long",
                    "source": "long_term",
                    "event_type": "long_term_summary",
                    "info": info,
                    "code": clean_memory_summary(str(payload.get("code") or "")),
                    "region": "",
                    "target": "",
                    "tags": ["long_term"],
                    "confidence": 0.78,
                }
            )
        return chunks

    def _read_jsonl(self, path: Path) -> list[dict]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        payloads = []
        for line in lines:
            if not line.strip():
                continue
            try:
                payloads.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return payloads

    def _rank_candidates(self, candidates: list[dict], *, question: str, since_timestamp: float) -> list[dict]:
        seen: set[str] = set()
        unique: list[dict] = []
        content_seen: set[str] = set()
        for item in candidates:
            key = str(item.get("chunk_id") or "")
            if key in seen:
                continue
            seen.add(key)
            if float(item.get("timestamp") or 0.0) < since_timestamp:
                continue
            payload = dict(item)
            if self._is_no_change_chunk(payload):
                continue
            if _is_empty_long_summary_placeholder(str(payload.get("info") or "")):
                continue
            if _is_content_identity_question(question) and self._should_drop_content_candidate(payload):
                continue
            payload["score"] = round(self._score(payload, question=question), 4)
            if payload["score"] >= self._minimum_score(question=question):
                content_key = self._normalized_content_key(payload)
                if content_key and content_key in content_seen:
                    continue
                if content_key:
                    content_seen.add(content_key)
                unique.append(payload)
        unique.sort(key=lambda item: (float(item.get("score") or 0.0), float(item.get("timestamp") or 0.0)), reverse=True)
        return unique

    def _score(self, item: dict, *, question: str) -> float:
        info = str(item.get("info") or "")
        score = float(item.get("confidence") or 0.0)
        content_identity_question = _is_content_identity_question(question)
        status_question = _question_prefers_alert_or_status(question)
        region = str(item.get("region") or "")
        region_slot = str(item.get("region_slot") or "")
        fact_kind = _fact_kind(info)
        structured_values = [
            str(item.get("k1") or ""),
            str(item.get("k2") or ""),
            str(item.get("k3") or ""),
            str(item.get("subj") or ""),
            str(item.get("ctx") or ""),
            str(item.get("bg") or ""),
        ]
        structured_text = " ".join(value for value in structured_values if value)
        if item.get("event_type") in {"target_window_changed", "window_title_changed", "compact_short_memory"}:
            score += 2.0
        if item.get("event_type") == "compact_memory_segment":
            score += 2.2
        if item.get("source") == "file_memory":
            score += 1.2
        if item.get("source") == "file_memory_compact":
            score += 1.8
        if item.get("layer") == "compact":
            score += 1.4
        if item.get("layer") == "long":
            score += 0.4
            if content_identity_question:
                score += 0.9
        if "主内容" in region:
            score += 2.4
        elif "全目标" in region:
            score += 0.8
        elif any(label in region for label in ["顶部", "底部", "左侧", "右侧"]):
            score += 0.5
        if _contains_title_like_text(info):
            score += 1.0
        if _is_generic_visual(info) and content_identity_question:
            score -= 4.0
        if fact_kind:
            score += 1.6
        if status_question and fact_kind == "状态":
            score += 3.2
        if status_question and _is_generic_visual(info):
            score -= 2.2
        if _question_prefers_content(question) and fact_kind in {"内容", "页面", "画面", "表单", "图表", "表格", "卡片"}:
            score += 2.0
        if content_identity_question and _structured_detail_match(item=item, question=question):
            score += 4.2
        combined = f"{structured_text} {info}".lower()
        for token in self._semantic_tokens(question):
            if _structured_field_contains(item=item, token=token, fields=("subj", "ctx", "bg")):
                score += 2.0
            elif _structured_field_contains(item=item, token=token, fields=("k2", "k3")):
                score += 1.6
            elif _structured_field_contains(item=item, token=token, fields=("k1", "scene", "region_slot", "pos", "sub")):
                score += 1.0
            elif token in combined:
                score += 0.6
        score += _structured_semantic_bonus(item=item, question=question)
        if status_question and region_slot in {"top", "right"}:
            score += 0.8
        if _looks_noisy(info):
            score -= 2.5
        if content_identity_question and _is_low_value_content_identity(info):
            score -= 2.0
        return score

    def _candidate_limit(self, *, question: str, limit: int) -> int:
        if _is_content_identity_question(question):
            return max(limit * 80, 1000)
        return limit * 4

    def _minimum_score(self, *, question: str) -> float:
        if _is_content_identity_question(question):
            return 2.0
        return 0.01

    def _should_drop_content_candidate(self, item: dict) -> bool:
        info = str(item.get("info") or "")
        return _looks_noisy(info) or _is_low_value_content_identity(info) or _is_short_non_title_fragment(info)

    def _is_no_change_chunk(self, item: dict) -> bool:
        info = clean_memory_summary(str(item.get("info") or ""))
        return (item.get("source") == "diff" or item.get("event_type") == "visual_change") and info.startswith("未检测到显著变化")

    def _prefer_title_facts(self, ranked: list[dict]) -> list[dict]:
        title_facts = [item for item in ranked if _is_title_fact(str(item.get("info") or ""))]
        return title_facts or ranked

    def _candidate_index_dirs(self, *, task_id: str, since_timestamp: float, now: float) -> list[Path]:
        dirs: list[Path] = []
        start_day = int(since_timestamp // 86400)
        end_day = int(now // 86400)
        for day in range(start_day, end_day + 1):
            timestamp = day * 86400.0
            dirs.append(self.task_index_dir(task_id, timestamp=timestamp))
        current_dir = self.task_index_dir(task_id)
        if current_dir not in dirs:
            dirs.append(current_dir)
        return dirs

    def _query_terms(self, question: str) -> list[str]:
        terms = []
        for token in self._semantic_tokens(question):
            if re.fullmatch(r"[\w\u4e00-\u9fff]{2,}", token):
                terms.append(token)
        return terms[:8]

    def _semantic_tokens(self, question: str) -> list[str]:
        raw_tokens = re.split(r"\s+|[，。！？、,.!?：:【】\\[\\]()（）/]+", str(question or "").lower())
        stopwords = {"最近", "刚刚", "什么", "内容", "页面", "视频", "文档", "有没有", "发生", "情况", "的是", "我在", "看的", "看了", "打开"}
        return [token for token in raw_tokens if token and len(token) >= 2 and token not in stopwords]

    def _build_answer(self, items: list[dict], *, minutes: int) -> str:
        if not items:
            return f"最近 {minutes} 分钟内未在轻量索引中找到足够相关的记忆。"
        return "；".join(f"{self._answer_item_text(item)}@{self._format_clock(float(item.get('timestamp') or 0.0))}" for item in items[:3])

    def _answer_item_text(self, item: dict) -> str:
        info = clean_memory_summary(str(item.get("info") or ""))
        region = clean_memory_summary(str(item.get("region") or ""))
        info = self._augment_info_with_code_details(item=item, info=info)
        if region and not info.startswith(f"{region}："):
            return f"{region}：{info}"
        return info

    def _target_label(self, target: dict) -> str:
        return clean_memory_summary(str(target.get("window_title") or target.get("process_name") or target.get("screen_id") or target.get("type") or ""))

    def _trim(self, value: str, limit: int) -> str:
        text = clean_memory_summary(value)
        return text if len(text) <= limit else text[: limit - 3] + "..."

    def _normalized_content_key(self, item: dict) -> str:
        info = clean_memory_summary(str(item.get("info") or ""))
        region = clean_memory_summary(str(item.get("region") or ""))
        code_bits = [
            clean_memory_summary(str(item.get("scene") or "")),
            clean_memory_summary(str(item.get("region_slot") or "")),
            clean_memory_summary(str(item.get("k1") or "")),
            clean_memory_summary(str(item.get("k2") or "")),
            clean_memory_summary(str(item.get("k3") or "")),
            clean_memory_summary(str(item.get("pos") or "")),
            clean_memory_summary(str(item.get("sub") or "")),
            clean_memory_summary(str(item.get("subj") or "")),
            clean_memory_summary(str(item.get("ctx") or "")),
            clean_memory_summary(str(item.get("bg") or "")),
        ]
        code_key = "|".join(bit for bit in code_bits if bit)
        if not info and not code_key:
            return ""
        return f"{region}|{code_key}|{info}".lower()

    def _augment_info_with_code_details(self, *, item: dict, info: str) -> str:
        values = [
            str(item.get("subj") or ""),
            str(item.get("ctx") or ""),
            str(item.get("bg") or ""),
            str(item.get("k1") or ""),
            str(item.get("k2") or ""),
            str(item.get("k3") or ""),
        ]
        values = [value for value in values if value]
        if not values or len(info) >= 18:
            return info
        extra = [value for value in values[1:3] if value and value not in info]
        if not extra:
            return info
        if "：" in info:
            return f"{info}，{'，'.join(extra[:2])}"
        return f"{info} {' '.join(extra[:2])}"

    def _compact_query_item(self, item: dict) -> dict:
        payload = {
            "id": str(item.get("chunk_id") or ""),
            "t": str(item.get("time") or self._format_timestamp(float(item.get("timestamp") or 0.0))),
            "info": clean_memory_summary(str(item.get("info") or "")),
            "score": round(float(item.get("score") or 0.0), 4),
        }
        code = clean_memory_summary(str(item.get("code") or ""))
        region = clean_memory_summary(str(item.get("region") or ""))
        if code:
            payload["code"] = code
        if region:
            payload["reg"] = region
        return payload

    def _format_timestamp(self, timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _format_clock(self, timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def _contains_title_like_text(text: str) -> bool:
    value = str(text or "")
    return len(value) >= 8 and any(marker in value for marker in ["？", "?", "！", "!", "【", "】", "：", ":", "->"])


def _is_title_fact(text: str) -> bool:
    value = str(text or "")
    if _looks_noisy(value):
        return False
    return any(marker in value for marker in ["窗口切换", "标题切换", "代表窗口切换"]) or (
        any("\u4e00" <= char <= "\u9fff" for char in value) and any(marker in value for marker in ["？", "【", "】", "->"])
    )


def _is_generic_visual(text: str) -> bool:
    value = str(text or "")
    return any(marker in value for marker in ["这张图片展示", "图中显示", "图中有", "多个缩略图", "视频列表", "播放次数和点赞数"])


def _is_content_identity_question(question: str) -> bool:
    value = str(question or "")
    return any(marker in value for marker in ["看了什么", "看的什么", "视频是什么", "文档是什么", "打开了什么", "具体内容", "页面内容", "主要内容", "画面内容", "内容是什么", "内容是什", "内容如何", "项目内容"])


def _question_prefers_content(question: str) -> bool:
    value = str(question or "")
    return any(marker in value for marker in ["内容", "页面", "画面", "文档", "视频", "图表", "表格", "卡片", "主要"])


def _question_prefers_alert_or_status(question: str) -> bool:
    value = str(question or "")
    return any(marker in value for marker in ["异常", "错误", "告警", "提示", "报警", "状态"])


def _fact_kind(text: str) -> str:
    value = str(text or "").strip()
    for prefix in ["页面", "弹窗", "图表", "表格", "列表", "内容", "画面", "卡片", "表单", "导航", "状态"]:
        if value.startswith(f"{prefix}："):
            return prefix
    return ""


def _looks_noisy(text: str) -> bool:
    value = str(text or "").strip()
    if not value or value.startswith(("OCR 未识别到文本", "OCR 低质量文本已降权")):
        return True
    if "\uffff" in value or "�" in value:
        return True
    chars = [char for char in value if not char.isspace()]
    if len(chars) < 3:
        return True
    useful = sum(1 for char in chars if "\u4e00" <= char <= "\u9fff" or char.isalpha())
    symbol_count = sum(1 for char in chars if not char.isalnum() and not ("\u4e00" <= char <= "\u9fff"))
    digit_count = sum(1 for char in chars if char.isdigit())
    cjk_count = sum(1 for char in chars if "\u4e00" <= char <= "\u9fff")
    ascii_alpha_count = sum(1 for char in chars if char.isascii() and char.isalpha())
    if useful / max(len(chars), 1) < 0.2:
        return True
    if cjk_count == 0 and symbol_count >= 3 and (digit_count + symbol_count) / max(len(chars), 1) > 0.45:
        return True
    if cjk_count == 0 and ascii_alpha_count <= 8 and symbol_count >= 2 and digit_count >= 4:
        return True
    if re.search(r"[A-Za-z]\*%[A-Za-z]\*", value):
        return True
    return False


def _is_low_value_content_identity(text: str) -> bool:
    value = str(text or "").strip()
    markers = [
        "多个视频缩略图",
        "播放次数和点赞数",
        "视频列表",
        "首页推荐",
        "推荐视频",
        "没有明显标题",
        "无法确定具体",
    ]
    return any(marker in value for marker in markers)


def _is_empty_long_summary_placeholder(text: str) -> bool:
    value = str(text or "").strip()
    return not value or value in {"该时间段内无高价值摘要", "无高价值摘要"} or "无高价值摘要" in value


def _is_short_non_title_fragment(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    has_cjk = any("\u4e00" <= char <= "\u9fff" for char in value)
    if has_cjk or _contains_title_like_text(value):
        return False
    alnum_count = sum(1 for char in value if char.isalnum())
    return len(value) <= 24 or alnum_count <= 12


def _parse_code_fields(code: str) -> dict[str, str]:
    fields = {"scene": "", "region_slot": "", "k1": "", "k2": "", "k3": "", "pos": "", "sub": "", "subj": "", "ctx": "", "bg": ""}
    key_map = {
        "scn": "scene",
        "scene": "scene",
        "reg": "region_slot",
        "k1": "k1",
        "k2": "k2",
        "k3": "k3",
        "pos": "pos",
        "sub": "sub",
        "subj": "subj",
        "ctx": "ctx",
        "bg": "bg",
    }
    for part in str(code or "").split("|"):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        target_key = key_map.get(key.strip())
        if not target_key:
            continue
        fields[target_key] = clean_memory_summary(raw.strip())
    return fields


def _structured_field_contains(*, item: dict, token: str, fields: tuple[str, ...]) -> bool:
    token_value = str(token or "").lower()
    if not token_value:
        return False
    for field in fields:
        value = str(item.get(field) or "").lower()
        if token_value and token_value in value:
            return True
        normalized = _normalize_slot_value(value).lower()
        if token_value and token_value in normalized:
            return True
    return False


def _structured_semantic_bonus(*, item: dict, question: str) -> float:
    bonus = 0.0
    tokens = re.split(r"\s+|[，。！？、,.!?：:【】\[\]()（）/]+", str(question or "").lower())
    for token in tokens:
        token = token.strip()
        if len(token) < 2:
            continue
        if _structured_field_contains(item=item, token=token, fields=("subj", "ctx", "bg")):
            bonus += 1.8
        elif _structured_field_contains(item=item, token=token, fields=("k2", "k3")):
            bonus += 1.4
        elif _structured_field_contains(item=item, token=token, fields=("k1", "pos", "sub")):
            bonus += 0.9
    condensed = re.sub(r"\s+", "", str(question or "").lower())
    for slot_value in _structured_slot_values(item):
        if len(slot_value) >= 3 and slot_value in condensed:
            bonus += 1.6
    return bonus


def _structured_detail_match(*, item: dict, question: str) -> bool:
    condensed = re.sub(r"\s+", "", str(question or "").lower())
    for slot_value in _structured_slot_values(item):
        if len(slot_value) < 3:
            continue
        if slot_value in condensed and (item.get("k2") or item.get("k3") or item.get("subj") or item.get("ctx") or item.get("bg")):
            return True
    return False


def _structured_slot_values(item: dict) -> list[str]:
    values: list[str] = []
    for key in ("k1", "k2", "k3", "pos", "sub", "subj", "ctx", "bg"):
        raw = str(item.get(key) or "").strip()
        if not raw:
            continue
        values.append(raw)
        normalized = _normalize_slot_value(raw)
        if normalized and normalized != raw:
            values.append(normalized)
    return values


def _normalize_slot_value(value: str) -> str:
    text = str(value or "").strip()
    if "：" in text:
        text = text.split("：", 1)[1].strip()
    elif ":" in text:
        text = text.split(":", 1)[1].strip()
    return text


def _parse_memory_time(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
