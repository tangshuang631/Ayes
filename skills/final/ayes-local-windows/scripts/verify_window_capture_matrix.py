#!/usr/bin/env python3
"""Generate a macOS window capture feasibility matrix."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import time

from ayes.capture.screen import MacOSScreenCapture
from ayes.targets.capture_matrix import build_capture_feasibility_rows
from ayes.targets.discovery.macos import MacOSWindowDiscovery


def main() -> int:
    discovery = MacOSWindowDiscovery()
    capture = MacOSScreenCapture()
    candidates = discovery.list_windows()
    capture_results = {}
    tested_candidates = []
    for candidate in candidates[:50]:
        result = capture.capture_window(candidate, timestamp=time.time())
        capture_results[candidate.window_id] = result
        tested_candidates.append(candidate)
    rows = build_capture_feasibility_rows(candidates, capture_results=capture_results)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_count": len(candidates),
        "tested_window_count": len(tested_candidates),
        "capture_matrix": [asdict(row) for row in rows[:30]],
        "summary": {
            "observable": sum(1 for row in rows if row.expected_capture_result == "recommended"),
            "best_effort": sum(1 for row in rows if row.expected_capture_result == "best_effort"),
            "metadata_only": sum(1 for row in rows if row.expected_capture_result == "metadata_only"),
            "actual_ok": sum(1 for row in rows if row.actual_capture_ok),
            "actual_failed": sum(1 for row in rows if row.actual_capture_status not in {"not_tested", "ok"}),
        },
    }
    output_path = Path("runtime/window_capture_matrix.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
