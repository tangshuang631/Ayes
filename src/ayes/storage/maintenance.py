"""Runtime storage status and cleanup helpers."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any, Dict, Iterable, Optional

from ayes.app.task_paths import safe_task_segment
from ayes.memory.search_index import MemorySearchIndex
from ayes.storage.sqlite_store import SQLiteStore


TASK_CATEGORY_DIRS = {
    "screenshots": "screenshots",
    "memory": "memory",
    "logs": "logs",
    "index": "index",
    "config": "config",
}

LEGACY_DIR_NAMES = {"evidence", "latest", "memory", "archive"}
LEGACY_FILE_NAMES = {"web-last-frame.png", "screen-preview-main.png", "ayes-server.log", "ayes-menubar.log"}
LEGACY_FILE_PREFIXES = ("window-preview-",)


def build_storage_status(*, runtime_dir: Path, sqlite_store: SQLiteStore) -> Dict[str, Any]:
    runtime = Path(runtime_dir).resolve()
    tasks = []
    for task in sqlite_store.list_tasks(limit=10000):
        task_id = str(task.get("task_id") or "")
        task_dirs = _find_task_dirs(runtime_dir=runtime, task_id=task_id)
        task_payload: Dict[str, Any] = {
            "task_id": task_id,
            "task_dir": str(task_dirs[-1]) if task_dirs else None,
            "task_dirs": [str(path) for path in task_dirs],
            "total_bytes": 0,
        }
        for key, dirname in TASK_CATEGORY_DIRS.items():
            size = sum(_path_size(task_dir / dirname) for task_dir in task_dirs)
            task_payload[f"{key}_bytes"] = size
            task_payload["total_bytes"] += size
        tasks.append(task_payload)
    legacy = _legacy_storage_status(runtime)
    db_path = Path(sqlite_store.db_path)
    return {
        "runtime_dir": str(runtime),
        "total_bytes": _path_size(runtime),
        "sqlite_db_path": str(db_path),
        "sqlite_db_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "tasks": tasks,
        "task_count": len(tasks),
        "root_legacy": legacy,
    }


def cleanup_storage(
    *,
    runtime_dir: Path,
    sqlite_store: SQLiteStore,
    search_index: MemorySearchIndex,
    task_id: Optional[str] = None,
    screenshots: bool = False,
    logs: bool = False,
    memory: bool = False,
    index: bool = False,
    legacy: bool = False,
    vacuum: bool = False,
    rebuild_index: bool = False,
) -> Dict[str, Any]:
    runtime = Path(runtime_dir).resolve()
    task_ids = [task_id] if task_id else [str(task.get("task_id") or "") for task in sqlite_store.list_tasks(limit=10000)]
    task_ids = [value for value in task_ids if value]
    cleanup: Dict[str, Any] = {
        "task_id": task_id,
        "screenshots": _empty_delete_result(),
        "logs": _empty_delete_result(),
        "memory": _empty_delete_result(),
        "index": _empty_delete_result(),
        "legacy": _empty_delete_result(),
        "index_rebuild": {"indexed_chunks": 0, "task_count": 0, "tasks": []},
        "sqlite_vacuum": None,
    }
    for item_task_id in task_ids:
        task_dirs = _find_task_dirs(runtime_dir=runtime, task_id=item_task_id)
        if not task_dirs:
            continue
        for task_dir in task_dirs:
            if screenshots:
                _merge_delete_result(cleanup["screenshots"], _delete_path(task_dir / "screenshots"))
            if logs:
                _merge_delete_result(cleanup["logs"], _delete_path(task_dir / "logs"))
            if memory:
                _merge_delete_result(cleanup["memory"], _delete_path(task_dir / "memory"))
        if index:
            result = search_index.delete_task_index(item_task_id)
            _merge_delete_result(cleanup["index"], result)
        if rebuild_index:
            result = search_index.rebuild_task_index(item_task_id, since_timestamp=0.0)
            cleanup["index_rebuild"]["indexed_chunks"] += int(result.get("indexed_chunks") or 0)
            cleanup["index_rebuild"]["task_count"] += 1
            cleanup["index_rebuild"]["tasks"].append(result)
    if legacy:
        cleanup["legacy"] = cleanup_legacy_runtime(runtime)
    if vacuum:
        cleanup["sqlite_vacuum"] = sqlite_store.vacuum()
    return cleanup


def cleanup_legacy_runtime(runtime_dir: Path) -> Dict[str, Any]:
    runtime = Path(runtime_dir).resolve()
    result = _empty_delete_result()
    for path in _legacy_paths(runtime):
        _merge_delete_result(result, _delete_path(path))
    return result


def _legacy_storage_status(runtime_dir: Path) -> Dict[str, Any]:
    items = []
    total_bytes = 0
    for path in _legacy_paths(runtime_dir):
        size = _path_size(path)
        if size <= 0 and not path.exists():
            continue
        items.append({"path": str(path), "bytes": size})
        total_bytes += size
    return {"total_bytes": total_bytes, "items": items, "count": len(items)}


def _legacy_paths(runtime_dir: Path) -> Iterable[Path]:
    if not runtime_dir.exists():
        return []
    paths = []
    for child in runtime_dir.iterdir():
        if child.name in LEGACY_DIR_NAMES or child.name in LEGACY_FILE_NAMES or any(child.name.startswith(prefix) for prefix in LEGACY_FILE_PREFIXES):
            paths.append(child)
    return paths


def _find_task_dirs(*, runtime_dir: Path, task_id: str) -> list[Path]:
    safe_id = safe_task_segment(task_id)
    tasks_root = runtime_dir / "tasks"
    if not tasks_root.exists():
        return []
    matches = sorted(tasks_root.glob(f"**/{safe_id}"))
    return [path for path in matches if path.is_dir()]


def _path_size(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        if not path.exists():
            return 0
        total = 0
        for child in path.rglob("*"):
            if child.is_file():
                total += child.stat().st_size
        return total
    except OSError:
        return 0


def _delete_path(path: Path) -> Dict[str, Any]:
    size = _path_size(path)
    result = _empty_delete_result()
    result["deleted_bytes"] = size
    result["paths"] = []
    if not path.exists():
        result["deleted_bytes"] = 0
        return result
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        result["deleted_paths"] = 1
        result["paths"].append(str(path))
    except OSError as exc:
        result["errors"].append({"path": str(path), "error": str(exc)})
        result["deleted_bytes"] = 0
    return result


def _empty_delete_result() -> Dict[str, Any]:
    return {"deleted_bytes": 0, "deleted_paths": 0, "paths": [], "errors": []}


def _merge_delete_result(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    target["deleted_bytes"] += int(source.get("deleted_bytes") or 0)
    target["deleted_paths"] += int(source.get("deleted_paths") or 0)
    target.setdefault("paths", []).extend(source.get("paths") or [])
    target.setdefault("errors", []).extend(source.get("errors") or [])
