"""OCR input and output structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ImageInput:
    image_path: Optional[str] = None
    image_bytes: Optional[bytes] = None
    width: Optional[int] = None
    height: Optional[int] = None
    source: Optional[str] = None
    window_id: Optional[str] = None
    region_id: Optional[str] = None
    timestamp: Optional[float] = None


@dataclass(frozen=True)
class OCRTextBlock:
    text: str
    confidence: float
    bbox: List[float] = field(default_factory=list)
    rect: Dict[str, float] = field(default_factory=dict)
    rect_norm: Dict[str, float] = field(default_factory=dict)
    coordinate_space: str = "image_pixels"
    line_index: Optional[int] = None
    block_type: Optional[str] = None


@dataclass(frozen=True)
class OCRResult:
    provider: str
    elapsed_ms: int
    full_text: str
    blocks: List[OCRTextBlock] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    char_count: int = 0
    raw: Optional[Dict[str, object]] = None
