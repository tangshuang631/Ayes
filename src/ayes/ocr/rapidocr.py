"""RapidOCR provider."""

from __future__ import annotations

import tempfile
import time
from typing import Dict, List

from ayes.ocr.models import ImageInput, OCRResult, OCRTextBlock

try:
    from rapidocr_onnxruntime import RapidOCR  # type: ignore
except ImportError:  # pragma: no cover
    RapidOCR = None


class RapidOCRProvider:
    name = "rapidocr"
    version = "1"

    def __init__(self) -> None:
        self.is_available = RapidOCR is not None
        self._engine = RapidOCR() if self.is_available else None

    def capabilities(self) -> Dict[str, object]:
        return {
            "languages": ["zh", "en"],
            "supports_angle_cls": True,
            "supports_layout": False,
            "supports_gpu": False,
            "supports_offline": True,
            "supports_multiplatform": True,
        }

    def recognize(self, image: ImageInput, options: dict | None = None) -> OCRResult:
        if not self.is_available or self._engine is None:
            raise RuntimeError("RapidOCR 当前不可用")
        start = time.time()
        source = image.image_path
        temp_path = None
        if source is None:
            if image.image_bytes is None:
                raise ValueError("OCR 输入必须提供 image_path 或 image_bytes")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp:
                temp.write(image.image_bytes)
                temp_path = temp.name
                source = temp_path
        result, _ = self._engine(source)
        blocks: List[OCRTextBlock] = []
        texts: List[str] = []
        for index, item in enumerate(result or []):
            bbox, text, confidence = item
            texts.append(text)
            flattened = [float(v) for point in bbox for v in point]
            blocks.append(
                OCRTextBlock(
                    text=text,
                    confidence=float(confidence),
                    bbox=flattened,
                    line_index=index,
                )
            )
        elapsed_ms = int((time.time() - start) * 1000)
        return OCRResult(
            provider=self.name,
            elapsed_ms=elapsed_ms,
            full_text="\n".join(texts).strip(),
            blocks=blocks,
            char_count=len("".join(texts).strip()),
            raw={"line_count": len(blocks)},
        )
