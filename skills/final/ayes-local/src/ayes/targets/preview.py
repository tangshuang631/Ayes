"""Target preview and grouping helpers for the Web workbench."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional
import time

from ayes.capture.screen import create_screen_capture
from ayes.targets.models import WindowCandidate


LOW_RESOLUTION_MAX_WIDTH = 500
LOW_RESOLUTION_MAX_HEIGHT = 500


class TargetPreviewService:
    def __init__(self, *, runtime_dir: Path, capture: Optional[object] = None) -> None:
        self.runtime_dir = runtime_dir
        self.capture = capture or create_screen_capture()

    def build_screen_target(self) -> dict:
        preview_path = self.capture_screen_preview(name="screen-preview-main.png")
        width = 0
        height = 0
        probe = self.capture.capture_main_display(timestamp=time.time())
        if probe.ok and probe.frame is not None:
            width = probe.frame.width
            height = probe.frame.height
        return {
            "screen_id": 1,
            "name": "主屏幕",
            "bounds": {"width": width, "height": height},
            "observability": {
                "code": "observable" if preview_path else "metadata_only",
                "label": "可观测" if preview_path else "仅有元数据",
                "has_pixels": bool(preview_path),
                "is_recommended": bool(preview_path),
            },
            "preview_path": preview_path,
        }

    def build_window_groups(self, windows: List[WindowCandidate]) -> dict:
        primary_windows: List[dict] = []
        collapsed_windows: List[dict] = []
        process_map: "OrderedDict[str, dict]" = OrderedDict()
        for candidate in windows:
            preview_path = self.capture_window_preview(candidate)
            item = {
                **asdict(candidate),
                "preview_path": preview_path,
                "is_collapsed_default": self._is_collapsed_default(candidate, preview_path),
            }
            if item["is_collapsed_default"]:
                collapsed_windows.append(item)
            else:
                primary_windows.append(item)
            process_key = f"{candidate.process_id}:{candidate.process_name}"
            existing = process_map.get(process_key)
            if existing is None or self._is_better_process_representative(item, existing):
                process_map[process_key] = {
                    "process_id": candidate.process_id,
                    "process_name": candidate.process_name,
                    "window_id": candidate.window_id,
                    "title": candidate.title,
                    "bounds": asdict(candidate.bounds),
                    "observability": asdict(candidate.observability),
                    "preview_path": preview_path,
                    "is_collapsed_default": self._is_collapsed_default(candidate, preview_path),
                }
        collapsed_processes = [item for item in process_map.values() if item["is_collapsed_default"]]
        primary_processes = [item for item in process_map.values() if not item["is_collapsed_default"]]
        return {
            "windows": primary_windows,
            "collapsed_windows": collapsed_windows,
            "processes": primary_processes,
            "collapsed_processes": collapsed_processes,
            "collapse_rule": {
                "max_width": LOW_RESOLUTION_MAX_WIDTH,
                "max_height": LOW_RESOLUTION_MAX_HEIGHT,
                "collapse_without_preview": True,
            },
        }

    def capture_screen_preview(self, *, name: str) -> Optional[str]:
        result = self.capture.capture_main_display(timestamp=time.time())
        if not result.ok or result.frame is None:
            return None
        path = self._runtime_path(name)
        path.write_bytes(result.frame.image_bytes)
        return f"/runtime/{path.name}"

    def capture_window_preview(self, candidate: WindowCandidate) -> Optional[str]:
        result = self.capture.capture_window(candidate, timestamp=time.time())
        if not result.ok or result.frame is None:
            return None
        path = self._runtime_path(f"window-preview-{candidate.window_id}.png")
        path.write_bytes(result.frame.image_bytes)
        return f"/runtime/{path.name}"

    def _runtime_path(self, name: str) -> Path:
        path = self.runtime_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _is_collapsed_default(self, candidate: WindowCandidate, preview_path: Optional[str]) -> bool:
        if preview_path is None:
            return True
        return candidate.bounds.width <= LOW_RESOLUTION_MAX_WIDTH and candidate.bounds.height <= LOW_RESOLUTION_MAX_HEIGHT

    def _is_better_process_representative(self, current: dict, existing: dict) -> bool:
        if bool(current["preview_path"]) != bool(existing["preview_path"]):
            return bool(current["preview_path"])
        current_area = current["bounds"]["width"] * current["bounds"]["height"]
        existing_area = existing["bounds"]["width"] * existing["bounds"]["height"]
        return current_area > existing_area
