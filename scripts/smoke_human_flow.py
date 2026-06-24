#!/usr/bin/env python3
"""Run a minimal human-verifiable HTTP smoke flow against a local Ayes service."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Dict


def request_json(base_url: str, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{base_url}{path}"
    if payload is None:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Ayes minimal human-verifiable smoke flow")
    parser.add_argument("--base-url", default="http://127.0.0.1:8770", help="Ayes service base url")
    parser.add_argument("--task-id", default="task_smoke_human_flow", help="task id used for this smoke run")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    task_id = args.task_id

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

    request_json(base_url, "/api/watch/load-configured", load_payload)
    request_json(base_url, "/api/watch/run-once", {})
    time.sleep(0.5)

    status = request_json(base_url, "/api/status")
    timeline = request_json(base_url, f"/api/timeline/recent?task_id={urllib.parse.quote(task_id)}&minutes=5&limit=20")
    snippets = request_json(base_url, f"/api/ocr/snippets?task_id={urllib.parse.quote(task_id)}&minutes=5&limit=20")
    logs = request_json(base_url, f"/api/logs?task_id={urllib.parse.quote(task_id)}&minutes=15")
    ask = request_json(base_url, f"/api/ask?task_id={urllib.parse.quote(task_id)}&question={urllib.parse.quote('最近发生了什么')}&minutes=5")
    memory_items = request_json(base_url, f"/api/memory/items?task_id={urllib.parse.quote(task_id)}&minutes=5&limit=20")

    timeline_items = timeline.get("items") or []
    snippet_items = snippets.get("items") or []
    ask_events = ask.get("matched_events") or []
    memory_entry_items = memory_items.get("items") or []

    summary = {
        "task_id": task_id,
        "status_has_runner": status.get("has_runner"),
        "timeline_event_count": len(timeline_items),
        "timeline_first_preview_overlay": (timeline_items[0] if timeline_items else {}).get("preview_overlay"),
        "snippet_count": len(snippet_items),
        "snippet_first_preview_overlay": (snippet_items[0] if snippet_items else {}).get("preview_overlay"),
        "snippet_first_evidence_ref": (snippet_items[0] if snippet_items else {}).get("evidence_ref"),
        "log_count": len(logs.get("items") or []),
        "ask_answer": ask.get("answer"),
        "ask_matched_event_count": len(ask_events),
        "ask_time_range": ask.get("time_range"),
        "memory_item_count": len(memory_entry_items),
        "memory_first_preview_overlay": (memory_entry_items[0] if memory_entry_items else {}).get("preview_overlay"),
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not status.get("has_runner"):
        print("smoke failed: service did not keep a loaded runner", file=sys.stderr)
        return 1
    if not isinstance(timeline_items, list):
        print("smoke failed: timeline items malformed", file=sys.stderr)
        return 1
    if not isinstance(snippet_items, list):
        print("smoke failed: snippet items malformed", file=sys.stderr)
        return 1
    if not isinstance(memory_entry_items, list):
        print("smoke failed: memory items malformed", file=sys.stderr)
        return 1
    if "answer" not in ask:
        print("smoke failed: ask response missing answer", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
