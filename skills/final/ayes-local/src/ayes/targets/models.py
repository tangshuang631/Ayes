"""Target models for screens and windows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class Bounds:
    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class ObservabilityStatus:
    code: str
    label: str
    has_pixels: bool
    is_recommended: bool


@dataclass(frozen=True)
class WindowCandidate:
    window_id: int
    process_id: int
    process_name: str
    title: str
    bounds: Bounds
    layer: int
    is_onscreen: bool
    observability: ObservabilityStatus
    is_business_candidate: bool
    metadata: Dict[str, object] = field(default_factory=dict)


def observability_from_flags(*, has_pixels: bool, is_onscreen: bool) -> ObservabilityStatus:
    if has_pixels and is_onscreen:
        return ObservabilityStatus("observable", "可观测", True, True)
    if has_pixels and not is_onscreen:
        return ObservabilityStatus("partial", "部分可观测", True, False)
    if not has_pixels:
        return ObservabilityStatus("metadata_only", "仅有元数据", False, False)
    return ObservabilityStatus("unavailable", "当前不可采集", False, False)


def infer_business_candidate(bounds: Bounds, layer: int, title: str) -> bool:
    if bounds.area < 20_000:
        return False
    if layer != 0:
        return False
    if title.strip():
        return True
    return bounds.width >= 300 and bounds.height >= 200
