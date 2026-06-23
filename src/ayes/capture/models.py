"""Capture data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class CaptureFrame:
    frame_id: str
    timestamp: float
    target_type: str
    target_id: str
    width: int
    height: int
    image_bytes: bytes
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CaptureResult:
    ok: bool
    status: str
    frame: Optional[CaptureFrame] = None
    message: str = ""
