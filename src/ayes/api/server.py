"""FastAPI server for Ayes Web workbench."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Optional
import time

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ayes.app.state import AppState
from ayes.cli.spec_builder import build_window_observe_spec
from ayes.config.models import WatchSpec


BASE_DIR = Path(__file__).resolve().parents[3]
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="Ayes Workbench")
state = AppState()

if (WEB_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
RUNTIME_DIR = BASE_DIR / "runtime"
if RUNTIME_DIR.exists():
    app.mount("/runtime", StaticFiles(directory=str(RUNTIME_DIR)), name="runtime")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/api/status")
def get_status() -> JSONResponse:
    return JSONResponse(state.status())


@app.get("/api/windows")
def list_windows() -> JSONResponse:
    state.log_store.write(category="api", level="info", message="读取窗口列表")
    windows = [asdict(item) for item in state.window_discovery.list_windows()]
    return JSONResponse({"items": windows})


@app.post("/api/specs/window/{window_id}")
def create_window_spec(window_id: int) -> JSONResponse:
    output_path = build_window_observe_spec(window_id=window_id, output_path="runtime/mvp-observe-window.json")
    state.log_store.write(category="api", level="info", message="生成窗口监控 spec", metadata={"window_id": window_id})
    return JSONResponse({"output_path": output_path, "window_id": window_id})


@app.post("/api/watch/load-screen")
def load_screen_watch() -> JSONResponse:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 500,
                "ocr_interval_ms": 500,
                "change_detection_interval_ms": 500,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec)
    state.log_store.write(category="watch", level="info", message="已装载屏幕监控任务", task_id="task_web")
    return JSONResponse({"status": "loaded", "mode": runner.spec.mode})


@app.post("/api/watch/load-window/{window_id}")
def load_window_watch(window_id: int) -> JSONResponse:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "window", "window_id": window_id},
            "sampling": {
                "screenshot_interval_ms": 500,
                "ocr_interval_ms": 500,
                "change_detection_interval_ms": 500,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    state.set_runner(spec)
    state.log_store.write(category="watch", level="info", message="已装载窗口监控任务", task_id="task_web", metadata={"window_id": window_id})
    return JSONResponse({"status": "loaded", "window_id": window_id})


@app.post("/api/watch/run-once")
def run_watch_once() -> JSONResponse:
    if state.current_runner is None:
        return JSONResponse({"error": "当前没有已装载监控任务"}, status_code=400)
    events = [asdict(event) for event in state.current_runner.run_once()]
    capture_result = state.current_runner.capture.capture_main_display(timestamp=time.time())
    if capture_result.ok and capture_result.frame is not None:
        screenshot_path = Path("runtime/web-last-frame.png")
        screenshot_path.write_bytes(capture_result.frame.image_bytes)
        state.last_screenshot_path = str(screenshot_path)
    state.log_store.write(category="watch", level="info", message="执行一次监控采样", task_id=state.current_task_id, metadata={"emitted_events": len(events)})
    return JSONResponse({"events": events, "status": state.status()})


@app.post("/api/watch/stop")
def stop_watch() -> JSONResponse:
    state.clear_runner()
    return JSONResponse({"status": state.status()})


@app.get("/api/events")
def get_events() -> JSONResponse:
    task_id = state.current_task_id
    if not task_id:
        return JSONResponse({"items": []})
    return JSONResponse({"items": state.sqlite_store.list_events(task_id=task_id, limit=100)})


@app.get("/api/memory/recent")
def get_recent_memory(minutes: int = Query(5, ge=1, le=15), keyword: Optional[str] = None) -> JSONResponse:
    if state.current_runner is None:
        return JSONResponse({"answer": "当前没有监控任务", "matched_events": []})
    result = state.current_runner.ask_recent(minutes=minutes, keyword=keyword)
    return JSONResponse(
        {
            "answer": result.answer,
            "confidence": result.confidence,
            "matched_events": [asdict(event) for event in result.matched_events],
            "memory_layers_used": result.memory_layers_used,
        }
    )


@app.get("/api/ask")
def ask_question(question: str = Query(...), minutes: int = Query(5, ge=1, le=15)) -> JSONResponse:
    if state.current_runner is None:
        return JSONResponse({"answer": "当前没有监控任务", "matched_events": []})
    cleaned_question = question.strip()
    keyword = None if cleaned_question in {"", "最近发生了什么", "最近几分钟发生了什么"} else cleaned_question
    result = state.current_runner.ask_recent(minutes=minutes, keyword=keyword)
    state.log_store.write(category="api", level="info", message="执行一次问答查询", task_id=state.current_task_id, metadata={"question": question})
    return JSONResponse(
        {
            "answer": result.answer,
            "confidence": result.confidence,
            "matched_events": [asdict(event) for event in result.matched_events],
            "memory_layers_used": result.memory_layers_used,
        }
    )


@app.get("/api/logs")
def get_logs(category: Optional[str] = None) -> JSONResponse:
    return JSONResponse({"items": state.sqlite_store.list_logs(category=category, task_id=state.current_task_id, limit=100)})


@app.get("/api/screenshot")
def get_screenshot() -> JSONResponse:
    if not state.last_screenshot_path:
        return JSONResponse({"path": None})
    path = state.last_screenshot_path
    if not path.startswith("/"):
        path = "/" + path
    return JSONResponse({"path": path})


@app.get("/api/watch/status")
def watch_status() -> JSONResponse:
    return JSONResponse(state.status())


@app.get("/api/watch/task/{task_id}")
def get_watch_task(task_id: str) -> JSONResponse:
    task = state.sqlite_store.get_task(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return JSONResponse(task)


@app.get("/api/timeline/recent")
def timeline_recent(task_id: Optional[str] = None, limit: int = Query(20, ge=1, le=200)) -> JSONResponse:
    resolved_task_id = task_id or state.current_task_id
    if not resolved_task_id:
        return JSONResponse({"items": []})
    return JSONResponse({"items": state.sqlite_store.list_events(task_id=resolved_task_id, limit=limit)})


@app.get("/api/timeline/long-term")
def timeline_long_term(task_id: Optional[str] = None, limit: int = Query(20, ge=1, le=100)) -> JSONResponse:
    resolved_task_id = task_id or state.current_task_id
    if not resolved_task_id:
        return JSONResponse({"items": []})
    return JSONResponse({"items": state.sqlite_store.list_long_term_summaries(task_id=resolved_task_id, limit=limit)})


@app.get("/api/agent/contracts")
def get_agent_contracts() -> JSONResponse:
    return JSONResponse(
        {
            "watch.create": "/api/watch/load-screen or /api/watch/load-window/{window_id}",
            "watch.status": "/api/watch/status",
            "watch.stop": "/api/watch/stop",
            "timeline.recent": "/api/timeline/recent",
            "timeline.query": "/api/ask",
            "logs.recent": "/api/logs",
        }
    )
