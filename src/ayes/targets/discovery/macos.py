"""macOS window discovery based on Quartz."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ayes.targets.models import Bounds, WindowCandidate, infer_business_candidate, observability_from_flags

try:
    import Quartz  # type: ignore
except ImportError:  # pragma: no cover - exercised by unit test through availability flag
    Quartz = None


class MacOSWindowDiscovery:
    """Enumerate macOS windows and convert them into user-facing candidates."""

    def __init__(self) -> None:
        self.is_available = Quartz is not None

    def list_windows(self) -> List[WindowCandidate]:
        if not self.is_available:
            return []
        options = Quartz.kCGWindowListOptionAll
        raw_windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
        return self._convert_raw_windows(raw_windows or [])

    def get_window_by_id(self, window_id: int) -> Optional[WindowCandidate]:
        for candidate in self.list_windows():
            if candidate.window_id == window_id:
                return candidate
        return None

    def _convert_raw_windows(self, raw_windows: Iterable[Dict[str, Any]]) -> List[WindowCandidate]:
        candidates: List[WindowCandidate] = []
        for item in raw_windows:
            candidate = self._convert_raw_window(item)
            if candidate is None:
                continue
            candidates.append(candidate)
        candidates.sort(
            key=lambda item: (
                not item.is_business_candidate,
                not item.observability.is_recommended,
                item.bounds.area * -1,
            )
        )
        return candidates

    def _convert_raw_window(self, raw: Dict[str, Any]) -> Optional[WindowCandidate]:
        window_id = raw.get("kCGWindowNumber")
        process_id = raw.get("kCGWindowOwnerPID")
        process_name = raw.get("kCGWindowOwnerName") or ""
        bounds_raw = raw.get("kCGWindowBounds") or {}
        width = int(bounds_raw.get("Width", 0))
        height = int(bounds_raw.get("Height", 0))
        if not window_id or not process_id or not process_name:
            return None
        if width <= 0 or height <= 0:
            return None
        bounds = Bounds(
            x=int(bounds_raw.get("X", 0)),
            y=int(bounds_raw.get("Y", 0)),
            width=width,
            height=height,
        )
        layer = int(raw.get("kCGWindowLayer", 0))
        title = str(raw.get("kCGWindowName") or "").strip()
        alpha = float(raw.get("kCGWindowAlpha", 1.0))
        is_onscreen = bool(raw.get("kCGWindowIsOnscreen", False))
        has_pixels = alpha > 0 and bounds.area > 0
        observability = observability_from_flags(has_pixels=has_pixels, is_onscreen=is_onscreen)
        return WindowCandidate(
            window_id=int(window_id),
            process_id=int(process_id),
            process_name=process_name,
            title=title,
            bounds=bounds,
            layer=layer,
            is_onscreen=is_onscreen,
            observability=observability,
            is_business_candidate=infer_business_candidate(bounds, layer, title),
            metadata={
                "alpha": alpha,
                "memory_usage": raw.get("kCGWindowMemoryUsage"),
                "sharing_state": raw.get("kCGWindowSharingState"),
            },
        )
