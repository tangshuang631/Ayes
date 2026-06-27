"""macOS window discovery based on Quartz."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
import re

from ayes.targets.models import Bounds, WindowCandidate, infer_business_candidate, observability_from_flags

try:
    import Quartz  # type: ignore
except ImportError:  # pragma: no cover - exercised by unit test through availability flag
    Quartz = None

try:
    from AppKit import NSRunningApplication, NSWorkspace  # type: ignore
except ImportError:  # pragma: no cover
    NSRunningApplication = None
    NSWorkspace = None


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

    def list_windows_for_process(
        self,
        *,
        process_name: Optional[str] = None,
        process_id: Optional[int] = None,
        only_observable: bool = True,
    ) -> List[WindowCandidate]:
        candidates = self._matching_process_candidates(process_name=process_name, process_id=process_id)
        if only_observable:
            candidates = [item for item in candidates if item.observability.is_recommended]
        return candidates

    def get_primary_window_for_process(
        self,
        *,
        process_name: Optional[str] = None,
        process_id: Optional[int] = None,
        only_observable: bool = True,
    ) -> Optional[WindowCandidate]:
        candidates = self.list_windows_for_process(
            process_name=process_name,
            process_id=process_id,
            only_observable=only_observable,
        )
        if not candidates:
            return None
        return max(candidates, key=self._process_window_rank)

    def activate_process(
        self,
        *,
        process_name: Optional[str] = None,
        process_id: Optional[int] = None,
    ) -> bool:
        if NSRunningApplication is None:
            return False
        apps = list(NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.tencent.xinWeChat") or [])
        apps.extend(list(NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.tencent.flue.WeChatAppEx") or []))
        if not apps:
            workspace_apps = list(NSRunningApplication.runningApplicationsWithBundleIdentifier_("") or [])
            apps = workspace_apps
        aliases = _process_name_aliases(process_name or "")
        activated = False
        for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.tencent.xinWeChat") or []:
            if process_id is not None and int(app.processIdentifier()) != int(process_id):
                continue
            app.activateWithOptions_(1 << 1)
            activated = True
        if activated:
            return True
        for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.tencent.flue.WeChatAppEx") or []:
            if process_id is not None and int(app.processIdentifier()) != int(process_id):
                continue
            app.activateWithOptions_(1 << 1)
            activated = True
        if activated:
            return True
        for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_("") or []:
            try:
                localized = str(app.localizedName() or "")
            except Exception:
                continue
            normalized = _normalize_process_token(localized)
            if process_id is not None and int(app.processIdentifier()) != int(process_id):
                continue
            if aliases and normalized not in aliases:
                continue
            app.activateWithOptions_(1 << 1)
            return True
        return False

    def get_frontmost_process_name(self) -> str:
        if NSWorkspace is None:
            return ""
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is None:
            return ""
        return str(front.localizedName() or "").strip()

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

    def _matches_process(
        self,
        candidate: WindowCandidate,
        *,
        process_name: Optional[str],
        process_id: Optional[int],
    ) -> bool:
        if process_id is not None and candidate.process_id != process_id:
            return False
        if process_name is not None and candidate.process_name.casefold() != process_name.casefold():
            return False
        return True

    def _matching_process_candidates(
        self,
        *,
        process_name: Optional[str],
        process_id: Optional[int],
    ) -> List[WindowCandidate]:
        windows = self.list_windows()
        if process_id is not None:
            windows = [item for item in windows if item.process_id == process_id]
        if not process_name:
            return windows
        exact = [item for item in windows if self._matches_process(item, process_name=process_name, process_id=process_id)]
        if exact:
            return exact
        aliases = _process_name_aliases(process_name)
        alias_matched = [item for item in windows if any(_same_process_name(item.process_name, alias) for alias in aliases)]
        if alias_matched:
            return alias_matched
        normalized_target = _normalize_process_token(process_name)
        partial = [
            item
            for item in windows
            if normalized_target and normalized_target in _normalize_process_token(item.process_name)
        ]
        if partial:
            return partial
        reverse_partial = [
            item
            for item in windows
            if normalized_target and _normalize_process_token(item.process_name) in normalized_target
        ]
        return reverse_partial

    def _process_window_rank(self, candidate: WindowCandidate) -> tuple:
        return (
            int(candidate.is_business_candidate),
            int(candidate.observability.is_recommended),
            int(candidate.observability.has_pixels),
            int(candidate.is_onscreen),
            int(bool(candidate.title.strip())),
            -candidate.layer,
            candidate.bounds.area,
        )


_PROCESS_NAME_ALIAS_MAP = {
    "微信": ["wechat", "wechatapex"],
    "weixin": ["wechat", "wechatapex"],
    "wechat": ["微信", "weixin", "wechatex", "wechatapex"],
    "哔哩哔哩": ["bilibili"],
    "b站": ["bilibili"],
    "bilibili": ["哔哩哔哩", "b站"],
    "谷歌浏览器": ["googlechrome", "chrome"],
    "chrome": ["googlechrome", "谷歌浏览器"],
}


def _normalize_process_token(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").casefold())


def _process_name_aliases(value: str) -> list[str]:
    normalized = _normalize_process_token(value)
    aliases = [normalized]
    aliases.extend(_PROCESS_NAME_ALIAS_MAP.get(normalized, []))
    return [_normalize_process_token(item) for item in aliases if _normalize_process_token(item)]


def _same_process_name(left: str, right: str) -> bool:
    return _normalize_process_token(left) == _normalize_process_token(right)
