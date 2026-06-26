"""Task-scoped runtime paths."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def safe_task_segment(value: str) -> str:
    text = str(value or "").strip() or "unknown"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)


def roi_task_segment(parent_task_id: str, roi_name: str) -> str:
    parent = safe_task_segment(parent_task_id)
    roi = safe_task_segment(roi_name)
    return f"{parent}__roi_{roi}" if roi else f"{parent}__roi"


def date_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(float(timestamp), timezone.utc).date().isoformat()


def date_from_task_id(task_id: str) -> str:
    text = str(task_id or "").strip()
    if len(text) >= 10:
        candidate = text[:10]
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
            return candidate
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def task_runtime_dir(runtime_dir: Path, task_id: str, *, timestamp: float | None = None) -> Path:
    date_text = date_from_timestamp(timestamp) if timestamp is not None else date_from_task_id(task_id)
    return Path(runtime_dir).resolve() / "tasks" / date_text / safe_task_segment(task_id)


def task_runtime_paths(runtime_dir: Path, task_id: str, *, timestamp: float | None = None) -> dict[str, Path]:
    root = task_runtime_dir(runtime_dir, task_id, timestamp=timestamp)
    roi_root = root / "roi"
    return {
        "task_dir": root,
        "roi_dir": roi_root,
        "screenshots_dir": root / "screenshots",
        "evidence_dir": root / "screenshots" / "evidence",
        "latest_dir": root / "screenshots" / "latest",
        "memory_dir": root / "memory",
        "config_dir": root / "config",
        "logs_dir": root / "logs",
    }


def roi_runtime_paths(runtime_dir: Path, parent_task_id: str, roi_task_id: str, *, timestamp: float | None = None) -> dict[str, Path]:
    parent_root = task_runtime_dir(runtime_dir, parent_task_id, timestamp=timestamp)
    root = parent_root / "roi" / safe_task_segment(roi_task_id)
    return {
        "task_dir": root,
        "roi_dir": root,
        "screenshots_dir": root / "screenshots",
        "evidence_dir": root / "screenshots" / "evidence",
        "latest_dir": root / "screenshots" / "latest",
        "memory_dir": root / "memory",
        "config_dir": root / "config",
        "logs_dir": root / "logs",
    }
