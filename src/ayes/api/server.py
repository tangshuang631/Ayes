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
from ayes.api.contracts import (
    build_agent_contract_payload,
    build_memory_items_payload,
    build_observe_live_payload,
    build_preview_overlay,
    build_query_result_payload,
    describe_location_summary,
    extract_structured_observation,
)
from ayes.cli.spec_builder import build_window_observe_spec
from ayes.config.models import WatchSpec
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability, Region, TimelineEvent, WatchMatch
from ayes.memory.short_term import QueryResult
from ayes.planner.service import WatchSpecPlanner
from ayes.targets.preview import TargetPreviewService
from ayes.vision.ollama import OllamaService


BASE_DIR = Path(__file__).resolve().parents[3]
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="Ayes Workbench")
state = AppState()
target_preview_service = TargetPreviewService(runtime_dir=BASE_DIR / "runtime")
ollama_service = OllamaService()
planner_service = WatchSpecPlanner()

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


def _decorate_event_payload(item: dict) -> dict:
    payload = dict(item)
    payload["location_summary"] = describe_location_summary(payload)
    payload["preview_overlay"] = build_preview_overlay(payload)
    payload["structured_observation"] = extract_structured_observation(payload)
    return payload


def _build_screenshot_payload() -> dict:
    if not state.last_screenshot_path:
        return {"path": None, "regions": [], "target": None, "capture_target": None, "capture_status": None, "capture_timestamp": None}
    path = state.last_screenshot_path
    if not path.startswith("/"):
        path = "/" + path
    regions = []
    if state.current_spec is not None:
        regions = [
            {
                "region_id": region.region_id,
                "name": region.name,
                "x": region.x,
                "y": region.y,
                "w": region.w,
                "h": region.h,
                "coordinate_space": region.coordinate_space,
            }
            for region in state.current_spec.target.regions
            if region.enabled
        ]
    current_status = state.status()
    return {
        "path": path,
        "regions": regions,
        "target": asdict(state.current_spec.target) if state.current_spec else None,
        "capture_target": current_status.get("last_capture_target"),
        "capture_status": current_status.get("last_capture_status"),
        "capture_timestamp": current_status.get("last_run_at"),
    }


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


def _build_long_term_query_result_from_store(*, task_id: str, hours: int, keyword: Optional[str]) -> QueryResult:
    items = state.sqlite_store.query_long_term_summaries(task_id=task_id, hours=hours, keyword=keyword, limit=100)
    if not items:
        return QueryResult(
            answer=f"最近 {hours} 小时内未发现相关长期摘要。",
            confidence=0.7,
            matched_events=[],
            memory_layers_used=["long_term_persisted"],
        )
    matched_events = []
    for item in items:
        matched_events.append(
            TimelineEvent(
                event_id=str(item.get("summary_id") or ""),
                task_id=task_id,
                spec_version="1.0",
                task_mode="observe",
                timestamp=float(item.get("window_end") or 0.0),
                source="long_term",
                event_type="long_term_summary",
                priority="medium",
                confidence=0.78,
                target=EventTarget(type="screen"),
                observability=Observability(True, False, False, True, "summary"),
                summary=str(item.get("summary") or ""),
            )
        )
    answer = "；".join(f"{item.get('summary') or '无摘要'}@{int(item.get('window_end') or 0)}" for item in items[-5:])
    return QueryResult(
        answer=answer,
        confidence=0.78,
        matched_events=matched_events[-5:],
        memory_layers_used=["long_term_persisted"],
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


@app.post("/api/agent/plan-watch-spec")
def plan_watch_spec(payload: dict = Body(...)) -> JSONResponse:
    task_id = str(payload.get("task_id") or "task_web").strip() or "task_web"
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt 不能为空"}, status_code=400)
    draft = planner_service.plan(
        task_id=task_id,
        prompt=prompt,
        target=payload.get("target"),
        webhook_url=payload.get("webhook_url"),
    )
    state.log_store.write(category="api", level="info", message="已生成 watch spec 草案", task_id=task_id, metadata={"mode": draft.mode})
    return JSONResponse(draft.to_dict())


@app.post("/api/watch/confirm-plan")
def confirm_watch_plan(payload: dict = Body(...)) -> JSONResponse:
    plan = payload.get("plan")
    confirmations = payload.get("confirmations") or {}
    try:
        spec, normalized_plan = planner_service.confirm(plan_payload=plan, confirmations=confirmations)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    task_id = str(normalized_plan.get("task_id") or payload.get("task_id") or "task_web").strip() or "task_web"
    state.set_runner(spec, task_id=task_id)
    state.log_store.write(category="watch", level="info", message="已从任务草案确认并装载监控任务", task_id=task_id, metadata={"mode": spec.mode, "target_type": spec.target.type})
    return JSONResponse(
        {
            "status": "loaded",
            "task_id": task_id,
            "mode": spec.mode,
            "target": asdict(spec.target),
            "spec": asdict(spec),
            "plan": normalized_plan,
        }
    )


@app.post("/api/watch/run-once")
def run_watch_once() -> JSONResponse:
    if state.current_runner is None:
        return JSONResponse({"error": "当前没有已装载监控任务"}, status_code=400)
    events = [asdict(event) for event in state.current_runner.run_once()]
    latest_frame = state.current_runner.last_captured_frame
    if latest_frame is not None:
        screenshot_path = Path("runtime/web-last-frame.png")
        screenshot_path.write_bytes(latest_frame.image_bytes)
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
        return JSONResponse({"items": [], "task_id": None, "minutes": minutes, "source": source, "count": 0})
    since_timestamp = time.time() - (minutes * 60)
    items = state.sqlite_store.list_events(
        task_id=resolved_task_id,
        source=source,
        since_timestamp=since_timestamp,
        limit=100,
    )
    items = [_decorate_event_payload(item) for item in items]
    return JSONResponse(
        {
            "items": items,
            "task_id": resolved_task_id,
            "minutes": minutes,
            "source": source,
            "count": len(items),
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


@app.get("/api/memory/items")
def get_memory_items(
    minutes: int = Query(5, ge=1, le=15),
    limit: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    task_id: Optional[str] = None,
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"task_id": None, "minutes": minutes, "limit": limit, "count": 0, "items": []})
    items = state.sqlite_store.query_events(
        task_id=resolved_task_id,
        minutes=minutes,
        keyword=keyword,
        limit=limit,
    )
    return JSONResponse(build_memory_items_payload(items=items, task_id=resolved_task_id, minutes=minutes, limit=limit))


@app.get("/api/ask")
def ask_question(
    question: str = Query(...),
    minutes: int = Query(5, ge=1, le=15),
    hours: Optional[int] = Query(None, ge=1, le=72),
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
    if hours is not None:
        result = _build_long_term_query_result_from_store(
            task_id=resolved_task_id,
            hours=hours,
            keyword=keyword,
        )
    elif state.current_runner is not None and resolved_task_id == state.current_task_id:
        result = state.current_runner.ask_recent(minutes=minutes, keyword=keyword, question=question)
    else:
        result = _build_query_result_from_store(
            task_id=resolved_task_id,
            minutes=minutes,
            keyword=keyword,
            question=question,
        )
    if hours is None and not result.matched_events:
        fallback_items = state.sqlite_store.query_events(
            task_id=resolved_task_id,
            minutes=minutes,
            limit=5,
        )
        if fallback_items:
            result = QueryResult(
                answer=result.answer,
                confidence=result.confidence,
                matched_events=[_event_from_payload(item) for item in fallback_items],
                memory_layers_used=result.memory_layers_used,
            )
    state.log_store.write(category="api", level="info", message="执行一次问答查询", task_id=resolved_task_id, metadata={"question": question, "minutes": minutes, "hours": hours})
    effective_minutes = (hours * 60) if hours is not None else minutes
    return JSONResponse(build_query_result_payload(result=result, minutes=effective_minutes, task_id=resolved_task_id, question=question))


@app.get("/api/logs")
def get_logs(
    category: Optional[str] = None,
    task_id: Optional[str] = None,
    minutes: Optional[int] = Query(None, ge=1, le=60),
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    since_timestamp = time.time() - (minutes * 60) if minutes else None
    items = state.sqlite_store.list_logs(category=category, task_id=resolved_task_id, since_timestamp=since_timestamp, limit=100)
    return JSONResponse(
        {
            "items": items,
            "task_id": resolved_task_id,
            "minutes": minutes,
            "category": category,
            "count": len(items),
        }
    )


@app.get("/api/alerts/recent")
def get_recent_alerts(
    task_id: Optional[str] = None,
    minutes: int = Query(15, ge=1, le=60),
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"items": [], "task_id": None, "minutes": minutes, "limit": limit, "count": 0})
    since_timestamp = time.time() - (minutes * 60)
    items = state.sqlite_store.list_events(task_id=resolved_task_id, source="alert", since_timestamp=since_timestamp, limit=limit)
    items = [_decorate_event_payload(item) for item in items]
    return JSONResponse(
        {
            "items": items,
            "task_id": resolved_task_id,
            "minutes": minutes,
            "limit": limit,
            "count": len(items),
        }
    )


@app.get("/api/ocr/snippets")
def get_ocr_snippets(
    task_id: Optional[str] = None,
    minutes: int = Query(5, ge=1, le=15),
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"items": [], "task_id": None, "minutes": minutes, "limit": limit, "count": 0})
    since_timestamp = time.time() - (minutes * 60)
    items = state.sqlite_store.list_events(task_id=resolved_task_id, source="ocr", since_timestamp=since_timestamp, limit=limit)
    snippets = []
    for item in items:
        item = _decorate_event_payload(item)
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
                "location_summary": item.get("location_summary"),
                "preview_overlay": item.get("preview_overlay"),
                "evidence_ref": ((item.get("evidence_refs") or [None])[0]),
                "tags": item.get("tags") or [],
                "structured_observation": item.get("structured_observation") or {},
            }
        )
    return JSONResponse(
        {
            "items": snippets,
            "task_id": resolved_task_id,
            "minutes": minutes,
            "limit": limit,
            "count": len(snippets),
        }
    )


@app.get("/api/screenshot")
def get_screenshot() -> JSONResponse:
    return JSONResponse(_build_screenshot_payload())


@app.get("/api/watch/status")
def watch_status() -> JSONResponse:
    return JSONResponse(state.status())


@app.get("/api/agent/observe-live")
def observe_live_context(
    task_id: Optional[str] = None,
    minutes: int = Query(5, ge=1, le=15),
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    observed_at = time.time()
    status_payload = state.status()
    screenshot_payload = _build_screenshot_payload()
    if not resolved_task_id:
        return JSONResponse(
            build_observe_live_payload(
                task_id="",
                minutes=minutes,
                limit=limit,
                status=status_payload,
                screenshot=screenshot_payload,
                recent_events=[],
                memory_items=[],
                alerts=[],
                logs=[],
                observed_at=observed_at,
            )
        )
    since_timestamp = observed_at - (minutes * 60)
    recent_events = state.sqlite_store.list_events(task_id=resolved_task_id, since_timestamp=since_timestamp, limit=limit)
    memory_items = state.sqlite_store.query_events(task_id=resolved_task_id, minutes=minutes, limit=limit)
    alerts = state.sqlite_store.list_events(task_id=resolved_task_id, source="alert", since_timestamp=since_timestamp, limit=limit)
    logs = state.sqlite_store.list_logs(task_id=resolved_task_id, since_timestamp=since_timestamp, limit=limit)
    return JSONResponse(
        build_observe_live_payload(
            task_id=resolved_task_id,
            minutes=minutes,
            limit=limit,
            status=status_payload,
            screenshot=screenshot_payload,
            recent_events=recent_events,
            memory_items=memory_items,
            alerts=alerts,
            logs=logs,
            observed_at=observed_at,
        )
    )


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
        return JSONResponse({"items": [], "task_id": None, "minutes": minutes, "limit": limit, "count": 0})
    since_timestamp = time.time() - (minutes * 60)
    items = state.sqlite_store.list_events(task_id=resolved_task_id, since_timestamp=since_timestamp, limit=limit)
    items = [_decorate_event_payload(item) for item in items]
    return JSONResponse(
        {
            "items": items,
            "task_id": resolved_task_id,
            "minutes": minutes,
            "limit": limit,
            "count": len(items),
        }
    )


@app.get("/api/timeline/long-term")
def timeline_long_term(task_id: Optional[str] = None, hours: Optional[int] = Query(None, ge=1, le=72), limit: int = Query(20, ge=1, le=100)) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"items": [], "task_id": None, "hours": hours, "limit": limit, "count": 0})
    items = state.sqlite_store.query_long_term_summaries(task_id=resolved_task_id, hours=hours, limit=limit) if hours is not None else state.sqlite_store.list_long_term_summaries(task_id=resolved_task_id, limit=limit)
    return JSONResponse({"items": items, "task_id": resolved_task_id, "hours": hours, "limit": limit, "count": len(items)})


@app.get("/api/agent/contracts")
def get_agent_contracts() -> JSONResponse:
    return JSONResponse(build_agent_contract_payload())
