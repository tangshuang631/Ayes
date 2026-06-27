"""Windows window discovery based on pygetwindow and psutil."""

from __future__ import annotations

from typing import Optional

from ayes.targets.models import Bounds, WindowCandidate, infer_business_candidate, observability_from_flags

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None

try:
    import pygetwindow as gw  # type: ignore
except ImportError:  # pragma: no cover
    gw = None


class WindowsWindowDiscovery:
    """Enumerate visible Windows desktop windows as Ayes candidates."""

    def __init__(self) -> None:
        self.is_available = psutil is not None and gw is not None

    def list_windows(self) -> list[WindowCandidate]:
        if not self.is_available:
            return []
        candidates: list[WindowCandidate] = []
        process_names = self._process_name_map()
        for index, window in enumerate(gw.getAllWindows() or [], start=1):
            candidate = self._convert_window(window, index=index, process_names=process_names)
            if candidate is not None:
                candidates.append(candidate)
        candidates.sort(
            key=lambda item: (
                not item.is_business_candidate,
                not item.observability.is_recommended,
                item.bounds.area * -1,
            )
        )
        return candidates

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
    ) -> list[WindowCandidate]:
        candidates = [
            item
            for item in self.list_windows()
            if self._matches_process(item, process_name=process_name, process_id=process_id)
        ]
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

    def _process_name_map(self) -> dict[int, str]:
        if psutil is None:
            return {}
        names: dict[int, str] = {}
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pid = int(proc.info.get("pid"))
                name = str(proc.info.get("name") or "")
            except (TypeError, ValueError, psutil.Error):
                continue
            if name:
                names[pid] = name
        return names

    def _convert_window(self, window: object, *, index: int, process_names: dict[int, str]) -> Optional[WindowCandidate]:
        title = str(getattr(window, "title", "") or "").strip()
        width = int(getattr(window, "width", 0) or 0)
        height = int(getattr(window, "height", 0) or 0)
        if width <= 0 or height <= 0:
            return None
        left = int(getattr(window, "left", 0) or 0)
        top = int(getattr(window, "top", 0) or 0)
        raw_handle = getattr(window, "_hWnd", None) or getattr(window, "hWnd", None) or index
        try:
            window_id = int(raw_handle)
        except (TypeError, ValueError):
            window_id = index
        process_id = int(getattr(window, "pid", 0) or 0)
        process_name = process_names.get(process_id) or title.split(" - ")[-1] or "Unknown"
        is_onscreen = not bool(getattr(window, "isMinimized", False))
        bounds = Bounds(x=left, y=top, width=width, height=height)
        observability = observability_from_flags(has_pixels=is_onscreen and bounds.area > 0, is_onscreen=is_onscreen)
        return WindowCandidate(
            window_id=window_id,
            process_id=process_id,
            process_name=process_name,
            title=title,
            bounds=bounds,
            layer=0,
            is_onscreen=is_onscreen,
            observability=observability,
            is_business_candidate=infer_business_candidate(bounds, 0, title),
            metadata={"backend": "pygetwindow"},
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

    def _process_window_rank(self, candidate: WindowCandidate) -> tuple:
        return (
            int(candidate.is_business_candidate),
            int(candidate.observability.is_recommended),
            int(candidate.observability.has_pixels),
            int(candidate.is_onscreen),
            int(bool(candidate.title.strip())),
            candidate.bounds.area,
        )
