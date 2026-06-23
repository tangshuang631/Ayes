"""Unified event structures for Ayes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class EventTarget:
    type: str
    process_name: Optional[str] = None
    process_id: Optional[int] = None
    window_id: Optional[int] = None
    screen_id: Optional[int] = None
    window_title: str = ""
    window_state: str = "unknown"


@dataclass(frozen=True)
class Observability:
    has_metadata: bool
    has_pixels: bool
    is_onscreen: bool
    is_observable_candidate: bool
    capture_status: str


@dataclass(frozen=True)
class Region:
    region_id: str = ""
    name: str = ""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    coordinate_space: str = "target"
    x_norm: float = 0.0
    y_norm: float = 0.0
    w_norm: float = 0.0
    h_norm: float = 0.0


@dataclass(frozen=True)
class EventTextBlock:
    text: str
    confidence: float
    bbox: List[float] = field(default_factory=list)
    line_index: Optional[int] = None
    block_type: Optional[str] = None


@dataclass(frozen=True)
class EventText:
    ocr_text: str = ""
    normalized_text: str = ""
    blocks: List[EventTextBlock] = field(default_factory=list)


@dataclass(frozen=True)
class EventVisual:
    summary: str = ""
    labels: List[str] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    provider: str = ""


@dataclass(frozen=True)
class WatchMatch:
    matched: bool = False
    score: float = 0.0
    matched_query: str = ""
    matched_rule: str = ""


@dataclass(frozen=True)
class TimelineEvent:
    event_id: str
    task_id: str
    spec_version: str
    task_mode: str
    timestamp: float
    source: str
    event_type: str
    priority: str
    confidence: float
    target: EventTarget
    observability: Observability
    region: Region = field(default_factory=Region)
    text: EventText = field(default_factory=EventText)
    visual: EventVisual = field(default_factory=EventVisual)
    summary: str = ""
    tags: List[str] = field(default_factory=list)
    watch_match: WatchMatch = field(default_factory=WatchMatch)
    evidence_refs: List[str] = field(default_factory=list)
    related_event_ids: List[str] = field(default_factory=list)
