"""macOS Vision based OCR provider."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Dict, List

from Foundation import NSURL  # type: ignore

from ayes.ocr.models import ImageInput, OCRResult, OCRTextBlock

try:
    import Vision  # type: ignore
except ImportError:  # pragma: no cover
    Vision = None


class VisionOCRProvider:
    name = "vision"
    version = "1"

    def __init__(self) -> None:
        self.is_available = Vision is not None

    def capabilities(self) -> Dict[str, object]:
        return {
            "languages": ["zh-Hans", "en-US"],
            "supports_angle_cls": False,
            "supports_layout": False,
            "supports_gpu": True,
            "supports_offline": True,
            "supports_multiplatform": False,
        }

    def recognize(self, image: ImageInput, options: dict | None = None) -> OCRResult:
        if not self.is_available:
            raise RuntimeError("Vision OCR 当前不可用")
        start = time.time()
        image_path = self._ensure_image_path(image)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        if hasattr(request, "setRecognitionLevel_"):
            request.setRecognitionLevel_(1)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(image_path), {})
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise RuntimeError(f"Vision OCR 执行失败: {error}")
        observations = request.results() or []
        blocks: List[OCRTextBlock] = []
        texts: List[str] = []
        for index, observation in enumerate(observations):
            top_candidates = observation.topCandidates_(1)
            if not top_candidates:
                continue
            candidate = top_candidates[0]
            text = str(candidate.string())
            confidence = float(candidate.confidence())
            texts.append(text)
            bbox = observation.boundingBox()
            blocks.append(
                OCRTextBlock(
                    text=text,
                    confidence=confidence,
                    bbox=[float(bbox.origin.x), float(bbox.origin.y), float(bbox.size.width), float(bbox.size.height)],
                    line_index=index,
                )
            )
        elapsed_ms = int((time.time() - start) * 1000)
        return OCRResult(
            provider=self.name,
            elapsed_ms=elapsed_ms,
            full_text="\n".join(texts).strip(),
            blocks=blocks,
            raw={"observation_count": len(observations)},
        )

    @staticmethod
    def _ensure_image_path(image: ImageInput) -> str:
        if image.image_path:
            return image.image_path
        if image.image_bytes is None:
            raise ValueError("OCR 输入必须提供 image_path 或 image_bytes")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp:
            temp.write(image.image_bytes)
            return temp.name
