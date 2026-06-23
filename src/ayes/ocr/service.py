"""OCR provider selection service."""

from __future__ import annotations

from typing import Iterable, List, Optional

from ayes.ocr.base import OCRProvider
from ayes.ocr.models import ImageInput, OCRResult
from ayes.ocr.rapidocr import RapidOCRProvider
from ayes.ocr.vision import VisionOCRProvider


class OCRService:
    def __init__(self, providers: Optional[Iterable[OCRProvider]] = None) -> None:
        self.providers: List[OCRProvider] = list(providers) if providers is not None else [
            VisionOCRProvider(),
            RapidOCRProvider(),
        ]

    def recognize(self, image: ImageInput, options: dict | None = None) -> OCRResult:
        errors: list[str] = []
        for provider in self.providers:
            try:
                return provider.recognize(image, options=options)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
        raise RuntimeError("所有 OCR provider 均失败: " + "; ".join(errors))
