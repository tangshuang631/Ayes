"""OCR provider selection service."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, List, Optional

from ayes.observation.text_quality import score_ocr_text
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
        if (options or {}).get("selection_mode") == "quality":
            return self._recognize_by_quality(image, options=options)
        errors: list[str] = []
        for provider in self.providers:
            try:
                return provider.recognize(image, options=options)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
        raise RuntimeError("所有 OCR provider 均失败: " + "; ".join(errors))

    def _recognize_by_quality(self, image: ImageInput, *, options: dict | None = None) -> OCRResult:
        errors: list[str] = []
        candidates: list[tuple[float, OCRResult, dict]] = []
        for provider in self.providers:
            try:
                result = provider.recognize(image, options=options)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            quality = score_ocr_text(
                result.full_text,
                block_confidences=[block.confidence for block in result.blocks],
            )
            candidate = {
                "provider": result.provider,
                "quality_score": quality.score,
                "avg_confidence": quality.avg_confidence,
                "gibberish_ratio": quality.gibberish_ratio,
                "char_count": result.char_count or len(result.full_text or ""),
                "is_noisy": quality.is_noisy,
            }
            candidates.append((quality.score, result, candidate))
        if not candidates:
            raise RuntimeError("所有 OCR provider 均失败: " + "; ".join(errors))
        selected = max(candidates, key=lambda item: item[0])[1]
        candidate_payload = [item[2] for item in candidates]
        raw = dict(selected.raw or {})
        raw.update(
            {
                "selected_by": "quality_score",
                "provider_candidates": candidate_payload,
            }
        )
        if errors:
            raw["provider_errors"] = errors
        return replace(selected, raw=raw)
