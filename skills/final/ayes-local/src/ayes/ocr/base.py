"""OCR provider base types."""

from __future__ import annotations

from typing import Dict, Protocol

from ayes.ocr.models import ImageInput, OCRResult


class OCRProvider(Protocol):
    name: str
    version: str

    def capabilities(self) -> Dict[str, object]:
        ...

    def recognize(self, image: ImageInput, options: dict | None = None) -> OCRResult:
        ...
