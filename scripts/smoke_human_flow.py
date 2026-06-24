#!/usr/bin/env python3
"""Run a minimal human-verifiable HTTP smoke flow against a local Ayes service."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Dict


DEFAULT_BASE_URL = "http://127.0.0.1:8770"


def ensure_project_src_on_path(root_dir: Path | None = None) -> Path:
    resolved_root = (root_dir or Path(__file__).resolve().parents[1]).resolve()
    src_dir = resolved_root / "src"
    src_text = str(src_dir)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
    return src_dir


ensure_project_src_on_path()

from ayes.app.service_control import default_service_config, ensure_service_started


def request_json(base_url: str, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{base_url}{path}"
    if payload is None:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def maybe_ensure_local_service_started(
    base_url: str,
    *,
    ensure_service_started_fn=None,
    default_base_url: str = DEFAULT_BASE_URL,
) -> None:
    if base_url.rstrip("/") != default_base_url.rstrip("/"):
        return
    callback = ensure_service_started_fn
    if callback is None:
        callback = lambda: ensure_service_started(default_service_config())
    callback()


def wait_for_service_ready(
    base_url: str,
    *,
    attempts: int = 20,
    sleep_sec: float = 0.5,
    request_json_fn=request_json,
) -> bool:
    for _ in range(max(attempts, 1)):
        try:
            payload = request_json_fn(base_url, "/api/status")
        except Exception:
            payload = None
        if isinstance(payload, dict):
            return True
        time.sleep(max(sleep_sec, 0))
    return False


def collect_smoke_summary(
    base_url: str,
    task_id: str,
    *,
    request_json_fn=request_json,
    sleep_sec: float = 0.5,
) -> Dict[str, Any]:
    load_payload = {
        "task_id": task_id,
        "mode": "observe",
        "target": {
            "type": "screen",
            "screen_id": 1,
            "regions": [
                {
                    "region_id": "roi_flow",
                    "name": "价格区",
                    "x": 0,
                    "y": 0,
                    "w": 200,
                    "h": 120,
                    "coordinate_space": "target",
                    "enabled": True,
                }
            ],
        },
        "sampling": {
            "screenshot_interval_ms": 1,
            "ocr_interval_ms": 1,
            "change_detection_interval_ms": 1,
            "max_fps": 2,
            "skip_ocr_when_no_change": False,
        },
        "watch_intent": {"enabled": False},
    }

    request_json_fn(base_url, "/api/watch/load-configured", load_payload)
    request_json_fn(base_url, "/api/watch/run-once", {})
    time.sleep(max(sleep_sec, 0))

    status = request_json_fn(base_url, "/api/status")
    timeline = request_json_fn(base_url, f"/api/timeline/recent?task_id={urllib.parse.quote(task_id)}&minutes=5&limit=20")
    snippets = request_json_fn(base_url, f"/api/ocr/snippets?task_id={urllib.parse.quote(task_id)}&minutes=5&limit=20")
    logs = request_json_fn(base_url, f"/api/logs?task_id={urllib.parse.quote(task_id)}&minutes=15")
    ask = request_json_fn(base_url, f"/api/ask?task_id={urllib.parse.quote(task_id)}&question={urllib.parse.quote('最近发生了什么')}&minutes=5")
    memory_items = request_json_fn(base_url, f"/api/memory/items?task_id={urllib.parse.quote(task_id)}&minutes=5&limit=20")
    screenshot = request_json_fn(base_url, f"/api/screenshot?task_id={urllib.parse.quote(task_id)}")

    timeline_items = timeline.get("items") or []
    snippet_items = snippets.get("items") or []
    ask_events = ask.get("matched_events") or []
    memory_entry_items = memory_items.get("items") or []
    ask_structured_vision_matches = ask.get("structured_vision_matches") or []
    ask_evidence_previews = ask.get("evidence_previews") or []
    vision_events = [item for item in timeline_items if item.get("source") == "vision"]
    ocr_events = [item for item in timeline_items if item.get("source") == "ocr"]

    return {
        "task_id": task_id,
        "status_has_runner": status.get("has_runner"),
        "status_last_ocr_quality": status.get("last_ocr_quality"),
        "status_last_vision_decision": status.get("last_vision_decision"),
        "status_last_vision_summary": status.get("last_vision_summary"),
        "status_latest_key_event": status.get("latest_key_event"),
        "status_recent_ocr_read": status.get("recent_ocr_read"),
        "status_activity_status": status.get("activity_status"),
        "timeline_event_count": len(timeline_items),
        "timeline_first_preview_overlay": (timeline_items[0] if timeline_items else {}).get("preview_overlay"),
        "timeline_first_ocr_quality": (((ocr_events[0] if ocr_events else {}).get("visual") or {}).get("attributes") or {}),
        "timeline_vision_event_count": len(vision_events),
        "snippet_count": len(snippet_items),
        "snippet_first_preview_overlay": (snippet_items[0] if snippet_items else {}).get("preview_overlay"),
        "snippet_first_evidence_ref": (snippet_items[0] if snippet_items else {}).get("evidence_ref"),
        "log_count": len(logs.get("items") or []),
        "ask_answer": ask.get("answer"),
        "ask_matched_event_count": len(ask_events),
        "ask_time_range": ask.get("time_range"),
        "ask_structured_vision_match_count": len(ask_structured_vision_matches),
        "ask_lead_evidence": ask.get("lead_evidence") or {},
        "ask_evidence_preview_count": len(ask_evidence_previews),
        "memory_item_count": len(memory_entry_items),
        "memory_first_preview_overlay": (memory_entry_items[0] if memory_entry_items else {}).get("preview_overlay"),
        "screenshot_path": screenshot.get("path"),
        "screenshot_capture_timestamp": screenshot.get("capture_timestamp"),
        "screenshot_capture_status": screenshot.get("capture_status"),
        "screenshot_capture_target": screenshot.get("capture_target"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ayes minimal human-verifiable smoke flow")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Ayes service base url")
    parser.add_argument("--task-id", default="task_smoke_human_flow", help="task id used for this smoke run")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    task_id = args.task_id

    maybe_ensure_local_service_started(base_url)
    if not wait_for_service_ready(base_url):
        print("smoke failed: service did not become ready in time", file=sys.stderr)
        return 1

    summary = collect_smoke_summary(base_url, task_id, request_json_fn=request_json, sleep_sec=0.5)

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not summary.get("status_has_runner"):
        print("smoke failed: service did not keep a loaded runner", file=sys.stderr)
        return 1
    if "ask_answer" not in summary:
        print("smoke failed: ask response missing answer", file=sys.stderr)
        return 1
    if "ask_structured_vision_match_count" not in summary:
        print("smoke failed: ask response missing structured_vision_matches", file=sys.stderr)
        return 1
    if "status_last_ocr_quality" not in summary:
        print("smoke failed: status missing last_ocr_quality", file=sys.stderr)
        return 1
    if "status_last_vision_decision" not in summary:
        print("smoke failed: status missing last_vision_decision", file=sys.stderr)
        return 1
    if "status_last_vision_summary" not in summary:
        print("smoke failed: status missing last_vision_summary", file=sys.stderr)
        return 1
    if "status_latest_key_event" not in summary:
        print("smoke failed: status missing latest_key_event", file=sys.stderr)
        return 1
    if "status_recent_ocr_read" not in summary:
        print("smoke failed: status missing recent_ocr_read", file=sys.stderr)
        return 1
    if "status_activity_status" not in summary:
        print("smoke failed: status missing activity_status", file=sys.stderr)
        return 1
    if "screenshot_capture_timestamp" not in summary:
        print("smoke failed: screenshot summary missing capture timestamp", file=sys.stderr)
        return 1
    if "ask_lead_evidence" not in summary:
        print("smoke failed: ask summary missing lead evidence", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
