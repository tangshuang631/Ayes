"""Structured outputs for optional vision augmentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class VisionResult:
    provider: str
    model: str
    summary: str
    labels: List[str] = field(default_factory=list)
    attributes: Dict[str, object] = field(default_factory=dict)
