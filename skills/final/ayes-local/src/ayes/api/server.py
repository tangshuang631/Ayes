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
from ayes.app.paths import repo_root, runtime_root
from ayes.api.contracts import (
    build_activity_payload,
    build_agent_contract_payload,
    build_memory_items_payload,
    build_observe_live_payload,
    build_preview_overlay,
    build_query_result_payload,
    build_region_bind_contract_payload,
    describe_location_summary,
    extract_structured_observation,
)
from ayes.cli.spec_builder import build_window_observe_spec
from ayes.config.models import (
    DEFAULT_SAMPLING_INTERVAL_MS,
    MAX_SAMPLING_INTERVAL_MS,
    MIN_SAMPLING_INTERVAL_MS,
    WatchSpec,
)
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability, Region, TimelineEvent, WatchMatch
from ayes.memory.short_term import QueryResult
from ayes.planner.service import WatchSpecPlanner
from ayes.targets.preview import TargetPreviewService
from ayes.vision.ollama import OllamaService


BASE_DIR = repo_root()
WEB_DIR = BASE_DIR / "web"
RUNTIME_DIR = runtime_root(BASE_DIR)

app = FastAPI(title="Ayes Workbench")
state = AppState()
target_preview_service = TargetPreviewService(runtime_dir=RUNTIME_DIR)
ollama_service = OllamaService()
planner_service = WatchSpecPlanner()

if (WEB_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
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
    state.persist_latest_screenshot()
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
        "image_width": state.last_screenshot_width,
        "image_height": state.last_screenshot_height,
        "regions": regions,
        "target": asdict(state.current_spec.target) if state.current_spec else None,
        "capture_target": current_status.get("last_capture_target"),
        "capture_status": current_status.get("last_capture_status"),
        "capture_timestamp": current_status.get("last_run_at"),
    }


def _build_ollama_status_payload(*, default_model: str) -> dict:
    settings = state.get_vision_enhancement_settings()
    selected_model = str(settings.get("model") or "").strip() or None
    recommended_default_model = "qwen2.5vl:7b"
    try:
        return ollama_service.status_report(default_model=recommended_default_model, selected_model=selected_model or default_model)
    except TypeError:
        return ollama_service.status_report()


def _build_vision_status_payload() -> dict:
    settings = state.get_vision_enhancement_settings()
    default_model = str(settings.get("model") or "qwen2.5vl:7b")
    provider_status = {}
    recommended_action = "check_on_user_enable_request"
    user_steps = [
        "仅当用户明确希望开启本地大模型增强时，再执行 vision prepare 做本地就绪检查。",
        "若 vision prepare 显示缺 Ollama、缺服务或缺默认模型，再按返回步骤安装、启动、拉取并启用。",
    ]
    agent_message = "当前默认本地视觉模型为 qwen2.5vl:7b。默认不主动检查 Ollama；只有用户明确希望开启本地大模型增强时，才应执行 vision prepare 做就绪检查。"
    agent_can_attempt_after_permission = True
    expected_effect = "本地视觉模型可辅助 skill 对截图进行结构化理解，并将结果写入事件、记忆、日志和回答链路。"
    return {
        "default_local_model": default_model,
        "readiness_check_required": True,
        "settings": settings,
        "provider_status": provider_status,
        "installation_guidance": {
            "agent_message": agent_message,
            "user_steps": user_steps,
            "agent_can_attempt_after_permission": agent_can_attempt_after_permission,
            "expected_effect": expected_effect,
        },
    }


def _build_vision_prepare_payload(*, requested_by: str) -> dict:
    settings = state.get_vision_enhancement_settings()
    default_model = str(settings.get("model") or "qwen2.5vl:7b")
    provider_status = _build_ollama_status_payload(default_model=default_model)
    recommended_action = str(provider_status.get("recommended_action") or "ready")
    user_steps = []
    agent_can_attempt_after_permission = False
    if recommended_action == "install_ollama":
        user_steps = [
            "先安装 Ollama 并启动本地服务。",
            "执行 ollama serve。",
            "执行 ollama pull qwen2.5vl:7b。",
            "再启用本地视觉增强。",
        ]
        agent_can_attempt_after_permission = True
    elif recommended_action == "start_service":
        user_steps = [
            "启动本地 Ollama 服务：ollama serve。",
            "确认服务可达后再启用本地视觉增强。",
        ]
        agent_can_attempt_after_permission = True
    elif recommended_action == "pull_default_model":
        user_steps = [
            "执行 ollama pull qwen2.5vl:7b。",
            "拉取完成后启用本地视觉增强。",
        ]
        agent_can_attempt_after_permission = True
    else:
        user_steps = [
            "本地视觉增强依赖已就绪，可直接启用。",
        ]
    return {
        "requested_by": requested_by,
        "default_local_model": default_model,
        "provider": "ollama",
        "provider_status": provider_status,
        "agent_can_attempt_after_permission": agent_can_attempt_after_permission,
        "user_steps": user_steps,
        "expected_effect": "启用后，本地视觉模型会在图表多、OCR 稀疏、按钮/布局理解等高视觉负载场景辅助 skill 进行结构化读取，并写入记忆、日志和回答。",
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
    if not items and keyword:
        items = state.sqlite_store.query_long_term_summaries(task_id=task_id, hours=hours, keyword=None, limit=100)
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


@app.get("/api/control/status")
def get_control_status() -> JSONResponse:
    return JSONResponse(state.control_status())


@app.post("/api/control/pause-all")
def pause_all_watches() -> JSONResponse:
    return JSONResponse({"status": state.pause_all_watches(reason="manual")})


@app.post("/api/control/resume-all")
def resume_all_watches() -> JSONResponse:
    return JSONResponse({"status": state.resume_all_watches()})


@app.get("/api/control/open-data-dir")
def open_data_dir(task_id: Optional[str] = None) -> JSONResponse:
    payload = state.control_status()
    resolved_task_id = task_id or state.current_task_id or state.last_task_id
    task_paths = state.current_task_paths(task_id=resolved_task_id)
    return JSONResponse(
        {
            "status": "ok",
            "task_id": resolved_task_id,
            "data_dir": task_paths["task_dir"],
            "task_dir": task_paths["task_dir"],
            "roi_dir": task_paths.get("roi_dir"),
            "screenshots_dir": task_paths["screenshots_dir"],
            "evidence_dir": task_paths["evidence_dir"],
            "memory_dir": task_paths["memory_dir"],
            "config_dir": task_paths["config_dir"],
            "logs_dir": task_paths["logs_dir"],
            "runtime_dir": payload["data_dir"],
            "archive_dir": payload["archive_dir"],
        }
    )


@app.get("/api/control/task-settings")
def get_task_settings(task_id: Optional[str] = None) -> JSONResponse:
    try:
        return JSONResponse({"settings": state.task_settings_snapshot(task_id=task_id)})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


@app.post("/api/control/cleanup-reminder")
def update_cleanup_reminder(payload: dict = Body(...)) -> JSONResponse:
    reminder = state.update_cleanup_reminder(
        suppress_forever=payload.get("suppress_forever"),
        snoozed_until=payload.get("snoozed_until"),
        last_prompt_at=payload.get("last_prompt_at"),
        next_check_after_days=payload.get("next_check_after_days"),
    )
    return JSONResponse({"status": "ok", "cleanup_reminder": reminder})


@app.post("/api/control/cleanup-reminder/check")
def check_cleanup_reminder(payload: dict = Body(...)) -> JSONResponse:
    result = state.check_cleanup_reminder_due(now=payload.get("now"))
    return JSONResponse(result)


@app.get("/api/control/settings")
def get_control_settings() -> JSONResponse:
    return JSONResponse({"settings": state.get_app_settings()})


@app.post("/api/control/settings")
def update_control_settings(payload: dict = Body(...)) -> JSONResponse:
    try:
        settings = state.update_app_settings(
            capture_screen_when_display_sleep=payload.get("capture_screen_when_display_sleep"),
            cleanup_reminder_days=payload.get("cleanup_reminder_days"),
            latest_frame_hotkey=payload.get("latest_frame_hotkey"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "ok", "settings": settings})


@app.get("/api/control/sampling")
def get_control_sampling(task_id: Optional[str] = None) -> JSONResponse:
    try:
        sampling = state.get_sampling_policy(task_id=task_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse(
        {
            "sampling": sampling,
            "limits": {
                "min_interval_ms": MIN_SAMPLING_INTERVAL_MS,
                "max_interval_ms": MAX_SAMPLING_INTERVAL_MS,
                "default_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
            },
        }
    )


@app.post("/api/control/sampling")
def update_control_sampling(payload: dict = Body(...)) -> JSONResponse:
    try:
        sampling = state.update_sampling_policy(
            task_id=payload.get("task_id"),
            interval_ms=payload.get("interval_ms"),
            quality=payload.get("quality"),
            save_ocr_screenshots=payload.get("save_ocr_screenshots"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "ok", "sampling": sampling})


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
    settings = state.get_vision_enhancement_settings()
    default_model = str(settings.get("model") or "qwen2.5vl:7b")
    return JSONResponse(_build_ollama_status_payload(default_model=default_model))


@app.get("/api/vision/settings")
def get_vision_settings() -> JSONResponse:
    return JSONResponse(state.get_vision_enhancement_settings())


@app.post("/api/vision/settings")
def update_vision_settings(payload: dict = Body(...)) -> JSONResponse:
    requested_enabled = bool(payload.get("enabled")) if payload.get("enabled") is not None else None
    requested_model = str(payload.get("model") or "").strip()
    warning = None
    if requested_enabled is True and requested_model:
        status_payload = _build_ollama_status_payload(default_model=requested_model)
        matched = next((item for item in status_payload.get("items", []) if str(item.get("name") or "") == requested_model), None)
        is_known_non_vision_model = matched is not None and not bool(matched.get("is_vision_model"))
        is_unknown_non_vision_model = matched is None and not OllamaService.is_vision_model_name(requested_model)
        if is_known_non_vision_model or is_unknown_non_vision_model:
            payload = dict(payload)
            payload["enabled"] = False
            warning = "当前选择增强模型为非视觉模型，已关闭本地模型增强。"
    settings = state.update_vision_enhancement_settings(
        enabled=payload.get("enabled"),
        provider=payload.get("provider"),
        model=payload.get("model"),
        auto_use_when_available=payload.get("auto_use_when_available"),
    )
    response_payload = {"status": "ok", "vision_settings": settings}
    if warning:
        response_payload["warning"] = warning
    return JSONResponse(response_payload)


@app.post("/api/vision/prepare")
def prepare_vision_enablement(payload: dict = Body(...)) -> JSONResponse:
    requested_by = str(payload.get("requested_by") or "user_enable_local_vision").strip() or "user_enable_local_vision"
    return JSONResponse(_build_vision_prepare_payload(requested_by=requested_by))


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
                "screenshot_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
                "ocr_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
                "change_detection_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
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
                "screenshot_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
                "ocr_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
                "change_detection_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
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
            "roi": payload.get("roi", {}),
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
            "memory_policy": state.get_task_memory_policy(task_id),
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


@app.post("/api/agent/region-bind-request")
def build_region_bind_request(payload: dict = Body(...)) -> JSONResponse:
    plan = payload.get("plan") or {}
    task_id = str(plan.get("task_id") or payload.get("task_id") or "").strip()
    target_ref = plan.get("resolved_target") or ((plan.get("draft_spec") or {}).get("target")) or {}
    capture_ref = payload.get("capture_ref") or {}
    if not capture_ref and state.last_screenshot_path:
        capture_ref = {
            "capture_id": f"cap_{task_id or 'latest'}",
            "image_path": state.last_screenshot_path if str(state.last_screenshot_path).startswith("/") else f"/{state.last_screenshot_path}",
            "image_width": state.last_screenshot_width,
            "image_height": state.last_screenshot_height,
        }
    region_intents = plan.get("region_intents") or []
    return JSONResponse(
        {
            "bind_version": "1.0",
            "task_id": task_id,
            "target_ref": target_ref,
            "capture_ref": capture_ref,
            "region_intents": region_intents,
        }
    )


@app.post("/api/agent/region-bind-result")
def accept_region_bind_result(payload: dict = Body(...)) -> JSONResponse:
    state.set_region_binding_context(
        {
            "task_id": payload.get("task_id"),
            "target_ref": payload.get("target_ref") or {},
            "capture_ref": payload.get("capture_ref") or {},
            "bindings": payload.get("region_bindings") or [],
            "unbound_region_intents": payload.get("unbound_region_intents") or [],
        }
    )
    return JSONResponse({"status": "accepted", "region_binding_context": state._last_region_binding_context or {}})


@app.get("/api/agent/region-bind-contract")
def get_region_bind_contract() -> JSONResponse:
    return JSONResponse(build_region_bind_contract_payload())


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
    state.set_region_binding_context(
        {
            "task_id": task_id,
            "target_ref": normalized_plan.get("resolved_target") or {},
            "capture_ref": confirmations.get("capture_ref") or {},
            "bindings": normalized_plan.get("region_bindings") or [],
            "unbound_region_intents": normalized_plan.get("unbound_region_intents") or [],
        }
    )
    state.log_store.write(category="watch", level="info", message="已从任务草案确认并装载监控任务", task_id=task_id, metadata={"mode": spec.mode, "target_type": spec.target.type})
    return JSONResponse(
        {
            "status": "loaded",
            "task_id": task_id,
            "mode": spec.mode,
            "target": asdict(spec.target),
            "spec": asdict(spec),
            "plan": normalized_plan,
            "memory_policy": state.get_task_memory_policy(task_id),
        }
    )


@app.post("/api/watch/run-once")
def run_watch_once() -> JSONResponse:
    if state.current_runner is None:
        return JSONResponse({"error": "当前没有已装载监控任务"}, status_code=400)
    events = [asdict(event) for event in state.current_runner.run_once()]
    state.persist_latest_screenshot()
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


@app.post("/api/watch/current/regions")
def add_current_region(payload: dict = Body(...)) -> JSONResponse:
    try:
        target = state.add_current_region(payload.get("region") or {})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "ok", "target": target, "watch_status": state.status()})


@app.delete("/api/watch/current/regions/{region_id}")
def delete_current_region(region_id: str) -> JSONResponse:
    try:
        target = state.delete_current_region(region_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "ok", "target": target, "watch_status": state.status()})


@app.get("/api/events")
def get_events(
    task_id: Optional[str] = None,
    source: Optional[str] = None,
    minutes: int = Query(5, ge=1, le=14 * 24 * 60),
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
    minutes: int = Query(5, ge=1, le=14 * 24 * 60),
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
    minutes: int = Query(5, ge=1, le=14 * 24 * 60),
    limit: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    task_id: Optional[str] = None,
    compact: bool = False,
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"task_id": None, "minutes": minutes, "limit": limit, "compact": compact, "count": 0, "items": []})
    items = state.sqlite_store.query_events(
        task_id=resolved_task_id,
        minutes=minutes,
        keyword=keyword,
        limit=limit,
    )
    return JSONResponse(build_memory_items_payload(items=items, task_id=resolved_task_id, minutes=minutes, limit=limit, compact=compact))


@app.get("/api/activity")
def get_activity_summary(
    task_id: Optional[str] = None,
    minutes: int = Query(5, ge=1, le=14 * 24 * 60),
) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    observed_at = time.time()
    if not resolved_task_id:
        return JSONResponse(
            build_activity_payload(
                items=[],
                task_id="",
                minutes=minutes,
                observed_at=observed_at,
                has_screenshot_evidence=False,
            )
        )
    items = state.sqlite_store.query_events(
        task_id=resolved_task_id,
        minutes=minutes,
        limit=20,
        now=observed_at,
    )
    has_screenshot_evidence = bool(state.last_screenshot_path)
    return JSONResponse(
        build_activity_payload(
            items=items,
            task_id=resolved_task_id,
            minutes=minutes,
            observed_at=observed_at,
            has_screenshot_evidence=has_screenshot_evidence,
        )
    )


@app.get("/api/ask")
def ask_question(
    question: str = Query(...),
    minutes: int = Query(5, ge=1, le=14 * 24 * 60),
    hours: Optional[int] = Query(None, ge=1, le=30 * 24),
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


@app.post("/api/tasks/{task_id}/screenshot/fresh")
def capture_task_fresh_screenshot(task_id: str) -> JSONResponse:
    try:
        payload = state.capture_task_screenshot(task_id=task_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    status_code = 200 if payload.get("capture_status") == "ok" else 409
    return JSONResponse(payload, status_code=status_code)


@app.get("/api/watch/status")
def watch_status() -> JSONResponse:
    return JSONResponse(state.status())


@app.get("/api/agent/observe-live")
def observe_live_context(
    task_id: Optional[str] = None,
    minutes: int = Query(5, ge=1, le=14 * 24 * 60),
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
                cleanup_reminder=state.get_cleanup_reminder(),
                region_binding_context=state._last_region_binding_context or {},
                vision_status=_build_vision_status_payload(),
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
            cleanup_reminder=state.get_cleanup_reminder(),
            region_binding_context=state._last_region_binding_context or {},
            vision_status=_build_vision_status_payload(),
            observed_at=observed_at,
        )
    )


@app.get("/api/watch/task/{task_id}")
def get_watch_task(task_id: str) -> JSONResponse:
    task = state.sqlite_store.get_task(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    task = dict(task)
    task["memory_policy"] = state.get_task_memory_policy(task_id)
    return JSONResponse(task)


@app.get("/api/tasks")
def list_watch_tasks(limit: int = Query(100, ge=1, le=500)) -> JSONResponse:
    items = state.list_tasks(limit=limit)
    return JSONResponse({"items": items, "count": len(items)})


@app.get("/api/tasks/{task_id}/roi")
def list_task_roi_children(task_id: str) -> JSONResponse:
    try:
        items = state.list_task_rois(parent_task_id=task_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"task_id": task_id, "items": items, "count": len(items)})


@app.post("/api/tasks/{task_id}/roi")
def create_task_roi_child(task_id: str, payload: dict = Body(...)) -> JSONResponse:
    try:
        result = state.create_roi_task(
            parent_task_id=task_id,
            roi_task_id=payload.get("roi_task_id"),
            roi_name=str(payload.get("roi_name") or "").strip(),
            region_payload=payload.get("region") or {},
            enabled=bool(payload.get("enabled", True)),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400 if "不能为空" in str(exc) else 404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "ok", **result})


@app.patch("/api/tasks/{task_id}/roi/{roi_task_id}")
def update_task_roi_child(task_id: str, roi_task_id: str, payload: dict = Body(...)) -> JSONResponse:
    try:
        result = state.update_roi_task(
            parent_task_id=task_id,
            roi_task_id=roi_task_id,
            roi_name=payload.get("roi_name"),
            enabled=payload.get("enabled"),
            region_payload=payload.get("region"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400 if "不能为空" in str(exc) else 404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "ok", **result})


@app.delete("/api/tasks/{task_id}/roi/{roi_task_id}")
def delete_task_roi_child(task_id: str, roi_task_id: str) -> JSONResponse:
    roi = state.sqlite_store.get_task_roi(roi_task_id)
    if roi is None or roi.get("parent_task_id") != task_id:
        return JSONResponse({"error": "ROI 子任务不存在"}, status_code=404)
    deleted = state.delete_task(roi_task_id)
    return JSONResponse({"status": "deleted", "task_id": roi_task_id, "parent_task_id": task_id, "deleted": deleted})


@app.get("/api/tasks/{task_id}/alert")
def get_task_alert_settings(task_id: str) -> JSONResponse:
    task = state.sqlite_store.get_task(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    spec = WatchSpec.from_dict(task["spec"])
    return JSONResponse({"task_id": task_id, "alert": asdict(spec.alert), "task_paths": state.current_task_paths(task_id=task_id)})


@app.post("/api/tasks/{task_id}/alert")
def update_task_alert_settings(task_id: str, payload: dict = Body(...)) -> JSONResponse:
    try:
        result = state.update_task_alert(task_id=task_id, alert_payload=payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "ok", **result})


@app.get("/api/tasks/{task_id}/memory-policy")
def get_task_memory_policy(task_id: str) -> JSONResponse:
    task = state.sqlite_store.get_task(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return JSONResponse({"memory_policy": state.get_task_memory_policy(task_id)})


@app.post("/api/tasks/{task_id}/memory-policy")
def update_task_memory_policy(task_id: str, payload: dict = Body(...)) -> JSONResponse:
    task = state.sqlite_store.get_task(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    try:
        policy = state.update_task_memory_policy(
            task_id=task_id,
            short_term_retain_days=payload.get("short_term_retain_days"),
            long_term_retain_days=payload.get("long_term_retain_days"),
            disable_auto_cleanup=payload.get("disable_auto_cleanup"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "ok", "memory_policy": policy})


@app.post("/api/tasks/{task_id}/memory-cleanup")
def run_task_memory_cleanup(task_id: str, payload: dict = Body(default={})) -> JSONResponse:
    task = state.sqlite_store.get_task(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return JSONResponse({"status": "ok", "cleanup": state.apply_memory_cleanup(task_id=task_id, now=payload.get("now"))})


@app.post("/api/watch/switch-task")
def switch_watch_task(payload: dict = Body(...)) -> JSONResponse:
    task_id = str(payload.get("task_id") or "").strip()
    if not task_id:
        return JSONResponse({"error": "task_id 不能为空"}, status_code=400)
    task = state.switch_task(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return JSONResponse({"status": "switched", "task": task, "watch_status": state.status()})


@app.delete("/api/watch/task/{task_id}")
def delete_watch_task(task_id: str) -> JSONResponse:
    task = state.sqlite_store.get_task(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    deleted = state.delete_task(task_id)
    return JSONResponse({"status": "deleted", "task_id": task_id, "deleted": deleted})


@app.get("/api/timeline/recent")
def timeline_recent(
    task_id: Optional[str] = None,
    minutes: int = Query(5, ge=1, le=14 * 24 * 60),
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
def timeline_long_term(task_id: Optional[str] = None, hours: Optional[int] = Query(None, ge=1, le=30 * 24), limit: int = Query(20, ge=1, le=100)) -> JSONResponse:
    resolved_task_id = _resolve_task_id(task_id)
    if not resolved_task_id:
        return JSONResponse({"items": [], "task_id": None, "hours": hours, "limit": limit, "count": 0})
    items = state.sqlite_store.query_long_term_summaries(task_id=resolved_task_id, hours=hours, limit=limit) if hours is not None else state.sqlite_store.list_long_term_summaries(task_id=resolved_task_id, limit=limit)
    return JSONResponse({"items": items, "task_id": resolved_task_id, "hours": hours, "limit": limit, "count": len(items)})


@app.get("/api/agent/contracts")
def get_agent_contracts() -> JSONResponse:
    return JSONResponse(build_agent_contract_payload())
