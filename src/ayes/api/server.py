"""FastAPI server for Ayes Web workbench."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Optional
import time

from fastapi import Body, FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ayes.app.state import AppState
from ayes.api.contracts import build_agent_contract_payload, build_preview_overlay, build_query_result_payload, describe_location_summary
from ayes.cli.spec_builder import build_window_observe_spec
from ayes.config.models import WatchSpec
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability, Region, TimelineEvent, WatchMatch
from ayes.memory.short_term import QueryResult
from ayes.targets.preview import TargetPreviewService
from ayes.vision.ollama import OllamaService


BASE_DIR = Path(__file__).resolve().parents[3]
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="Ayes Workbench")
state = AppState()
target_preview_service = TargetPreviewService(runtime_dir=BASE_DIR / "runtime")
ollama_service = OllamaService()

if (WEB_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
RUNTIME_DIR = BASE_DIR / "runtime"
if RUNTIME_DIR.exists():
    app.mount("/runtime", StaticFiles(directory=str(RUNTIME_DIR)), name="runtime")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


def _resolve_task_id(task_id: Optional[str]) -> Optional[str]:
    return task_id or state.current_task_id or state.last_task_id


def _runtime_path(name: str) -> Path:
    path = RUNTIME_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _build_query_result_from_store(*, task_id: str, minutes: int, keyword: Optional[str], question: str) -> QueryResult:
    items = state.sqlite_store.query_events(task_id=task_id, minutes=minutes, keyword=keyword, limit=100)
    matched_events = [_event_from_payload(item) for item in items]
    from ayes.memory.short_term import ShortTermMemoryStore

    temp_store = ShortTermMemoryStore(retain_seconds=minutes * 60)
    for event in matched_events:
        temp_store.append(event)
    result = temp_store.query(now=time.time(), minutes=minutes, keyword=keyword, question=question)
    if matched_events:
        return QueryResult(
            answer=result.answer,
            confidence=result.confidence,
            matched_events=result.matched_events or matched_events,
            memory_layers_used=["short_term_persisted"],
        )
    if not items:
        return QueryResult(
            answer=f"最近 {minutes} 分钟内未发现相关事件。",
            confidence=0.72,
            matched_events=[],
            memory_layers_used=["short_term_persisted"],
        )
    answer = "；".join(f"{item.get('summary') or item.get('event_type')}@{int(item.get('timestamp', 0))}" for item in items[-5:])
    return QueryResult(
        answer=answer,
        confidence=0.8,
        matched_events=[],
        memory_layers_used=["short_term_persisted"],
    )


def _event_from_payload(item: dict) -> TimelineEvent:
    text_payload = item.get("text") or {}
    block_payloads = text_payload.get("blocks") or []
    return TimelineEvent(
        event_id=item["event_id"],
        task_id=item["task_id"],
        spec_version=item["spec_version"],
        task_mode=item["task_mode"],
        timestamp=item["timestamp"],
        source=item["source"],
        event_type=item["event_type"],
        priority=item["priority"],
        confidence=item["confidence"],
        target=EventTarget(**(item.get("target") or {})),
        observability=Observability(**(item.get("observability") or {})),
        region=Region(**(item.get("region") or {})),
        text=EventText(
            ocr_text=text_payload.get("ocr_text", ""),
            normalized_text=text_payload.get("normalized_text", ""),
            blocks=[EventTextBlock(**block) for block in block_payloads],
        ),
        visual=EventVisual(**(item.get("visual") or {})),
        summary=item.get("summary", ""),
        tags=item.get("tags") or [],
        watch_match=WatchMatch(**(item.get("watch_match") or {})),
        evidence_refs=item.get("evidence_refs") or [],
        related_event_ids=item.get("related_event_ids") or [],
    )


@app.get("/api/status")
def get_status() -> JSONResponse:
    return JSONResponse(state.status())


@app.post("/api/app/session-open")
def open_app_session(payload: dict = Body(...)) -> JSONResponse:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse({"error": "session_id 不能为空"}, status_code=400)
    count = state.register_frontend_session(session_id)
    return JSONResponse({"connected_frontends": count, "status": state.status()})


@app.post("/api/app/session-heartbeat")
def heartbeat_app_session(payload: dict = Body(...)) -> JSONResponse:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse({"error": "session_id 不能为空"}, status_code=400)
    count = state.touch_frontend_session(session_id)
    return JSONResponse({"connected_frontends": count, "status": state.status()})


@app.post("/api/app/session-close")
def close_app_session(payload: dict = Body(...)) -> JSONResponse:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse({"error": "session_id 不能为空"}, status_code=400)
    count = state.unregister_frontend_session(session_id)
    return JSONResponse({"connected_frontends": count, "status": state.status()})


@app.get("/api/app/can-shutdown")
def can_shutdown_service() -> JSONResponse:
    return JSONResponse(
        {
            "can_shutdown_service": state.can_shutdown_service(),
            "status": state.status(),
        }
    )


@app.get("/api/windows")
def list_windows() -> JSONResponse:
    state.log_store.write(category="api", level="info", message="读取窗口列表")
    windows = [asdict(item) for item in state.window_discovery.list_windows()]
    return JSONResponse({"items": windows})


@app.get("/api/targets")
def list_targets() -> JSONResponse:
    state.log_store.write(category="api", level="info", message="读取监控目标候选")
    window_candidates = state.window_discovery.list_windows()
    grouped = target_preview_service.build_window_groups(window_candidates)
    screen = target_preview_service.build_screen_target()
    return JSONResponse({"screens": [screen], **grouped})


@app.get("/api/vision/models")
def list_vision_models() -> JSONResponse:
    items = ollama_service.list_models()
    return JSONResponse({"available": ollama_service.is_available(), "items": items})


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


@app.post("/api/watch/load-configured")
def load_configured_watch(payload: dict = Body(...)) -> JSONResponse:
    task_id = str(payload.get("task_id") or "task_web").strip() or "task_web"
    spec = WatchSpec.from_dict(
        {
            "spec_version": payload.get("spec_version", "1.0"),
            "mode": payload.get("mode", "observe"),
            "target": payload.get("target", {}),
            "sampling": payload.get("sampling", {}),
            "vision": payload.get("vision", {}),
            "memory": payload.get("memory", {}),
            "watch_intent": payload.get("watch_intent", {}),
            "alert": payload.get("alert", {}),
            "actions": payload.get("actions", {}),
        }
    )
    state.set_runner(spec, task_id=task_id)
    state.log_store.write(
        category="watch",
        level="info",
        message="已装载配置化监控任务",
        task_id=task_id,
        metadata={"mode": spec.mode, "target_type": spec.target.type},
    )
    return JSONResponse(
        {
            "status": "loaded",
            "task_id": task_id,
            "mode": spec.mode,
            "target": asdict(spec.target),
            "spec": asdict(spec),
        }
    )


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


@app.post("/api/watch/start")
def start_watch() -> JSONResponse:
    if state.current_runner is None:
        return JSONResponse({"error": "当前没有已装载监控任务"}, status_code=400)
    started = state.start_background_watch()
    if not started:
        return JSONResponse({"error": "后台持续监控启动失败"}, status_code=400)
    return JSONResponse({"status": state.status()})


@app.post("/api/watch/stop")
def stop_watch() -> JSONResponse:
    state.clear_runner()
    return JSONResponse({"status": state.status()})


@app.get("/api/events")
def get_events(
    task_id: Optional[str] = None,
    source: Optional[str] = None,
    minutes: int = Query(5, ge=1, le=15),
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"items": []})
    since_timestamp = time.time() - (minutes * 60)
    return JSONResponse(
        {
            "items": state.sqlite_store.list_events(
                task_id=resolved_task_id,
                source=source,
                since_timestamp=since_timestamp,
                limit=100,
            )
        }
    )


@app.get("/api/memory/recent")
def get_recent_memory(
    minutes: int = Query(5, ge=1, le=15),
    keyword: Optional[str] = None,
    task_id: Optional[str] = None,
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"answer": "当前没有监控任务", "matched_events": []})
    result = _build_query_result_from_store(
        task_id=resolved_task_id,
        minutes=minutes,
        keyword=keyword,
        question=keyword or "最近发生了什么",
    )
    return JSONResponse(build_query_result_payload(result=result, minutes=minutes, task_id=resolved_task_id, question=keyword or "最近发生了什么"))


@app.get("/api/ask")
def ask_question(
    question: str = Query(...),
    minutes: int = Query(5, ge=1, le=15),
    task_id: Optional[str] = None,
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"answer": "当前没有监控任务", "matched_events": []})
    cleaned_question = question.strip()
    if cleaned_question in {"", "最近发生了什么", "最近几分钟发生了什么"}:
        keyword = None
    elif any(token in cleaned_question for token in ["低于", "高于", "小于", "大于"]):
        keyword = None
    else:
        keyword = cleaned_question
    if state.current_runner is not None and resolved_task_id == state.current_task_id:
        result = state.current_runner.ask_recent(minutes=minutes, keyword=keyword, question=question)
    else:
        result = _build_query_result_from_store(
            task_id=resolved_task_id,
            minutes=minutes,
            keyword=keyword,
            question=question,
        )
    state.log_store.write(category="api", level="info", message="执行一次问答查询", task_id=resolved_task_id, metadata={"question": question, "minutes": minutes})
    return JSONResponse(build_query_result_payload(result=result, minutes=minutes, task_id=resolved_task_id, question=question))


@app.get("/api/logs")
def get_logs(
    category: Optional[str] = None,
    task_id: Optional[str] = None,
    minutes: Optional[int] = Query(None, ge=1, le=60),
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    since_timestamp = time.time() - (minutes * 60) if minutes else None
    return JSONResponse({"items": state.sqlite_store.list_logs(category=category, task_id=resolved_task_id, since_timestamp=since_timestamp, limit=100)})


@app.get("/api/ocr/snippets")
def get_ocr_snippets(
    task_id: Optional[str] = None,
    minutes: int = Query(5, ge=1, le=15),
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"items": []})
    since_timestamp = time.time() - (minutes * 60)
    items = state.sqlite_store.list_events(task_id=resolved_task_id, source="ocr", since_timestamp=since_timestamp, limit=limit)
    snippets = []
    for item in items:
        text = (item.get("text") or {}).get("ocr_text", "").strip()
        summary = (item.get("summary") or "").strip()
        if not text and not summary:
            continue
        snippets.append(
            {
                "event_id": item.get("event_id"),
                "timestamp": item.get("timestamp"),
                "summary": summary,
                "ocr_text": text,
                "preview": (text or summary)[:120],
                "location_summary": describe_location_summary(item),
                "preview_overlay": build_preview_overlay(item),
                "evidence_ref": ((item.get("evidence_refs") or [None])[0]),
                "tags": item.get("tags") or [],
            }
        )
    return JSONResponse({"items": snippets})


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
def timeline_recent(
    task_id: Optional[str] = None,
    minutes: int = Query(5, ge=1, le=15),
    limit: int = Query(20, ge=1, le=200),
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"items": []})
    since_timestamp = time.time() - (minutes * 60)
    items = state.sqlite_store.list_events(task_id=resolved_task_id, since_timestamp=since_timestamp, limit=limit)
    for item in items:
        item["location_summary"] = describe_location_summary(item)
        item["preview_overlay"] = build_preview_overlay(item)
    return JSONResponse({"items": items})


@app.get("/api/timeline/long-term")
def timeline_long_term(task_id: Optional[str] = None, limit: int = Query(20, ge=1, le=100)) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"items": []})
    return JSONResponse({"items": state.sqlite_store.list_long_term_summaries(task_id=resolved_task_id, limit=limit)})


@app.get("/api/agent/contracts")
def get_agent_contracts() -> JSONResponse:
    return JSONResponse(build_agent_contract_payload())
