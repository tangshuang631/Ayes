from ayes.ocr.models import ImageInput, OCRResult, OCRTextBlock
from ayes.ocr.service import OCRService


class FailingProvider:
    name = "fail"
    version = "1"

    def capabilities(self):
        return {}

    def recognize(self, image, options=None):
        raise RuntimeError("fail")


class SuccessProvider:
    name = "ok"
    version = "1"

    def capabilities(self):
        return {}

    def recognize(self, image, options=None):
        return OCRResult(provider="ok", elapsed_ms=1, full_text="hello")


def test_ocr_service_falls_back_to_next_provider() -> None:
    service = OCRService(providers=[FailingProvider(), SuccessProvider()])
    result = service.recognize(ImageInput(image_bytes=b"fake"))
    assert result.provider == "ok"
    assert result.full_text == "hello"


class NoisyProvider:
    name = "vision"
    version = "1"

    def capabilities(self):
        return {}

    def recognize(self, image, options=None):
        return OCRResult(
            provider="vision",
            elapsed_ms=2,
            full_text="KIkIl\ufffd8YeSJX 0OCg0,",
            char_count=len("KIkIl\ufffd8YeSJX 0OCg0,"),
            blocks=[OCRTextBlock(text="KIkIl\ufffd8YeSJX", confidence=0.28)],
        )


class ReadableProvider:
    name = "rapidocr"
    version = "1"

    def capabilities(self):
        return {}

    def recognize(self, image, options=None):
        return OCRResult(
            provider="rapidocr",
            elapsed_ms=5,
            full_text="Apifox 登录页 正在等待扫码登录",
            char_count=len("Apifox 登录页 正在等待扫码登录"),
            blocks=[OCRTextBlock(text="Apifox 登录页", confidence=0.91), OCRTextBlock(text="正在等待扫码登录", confidence=0.88)],
        )


def test_ocr_service_quality_selects_more_readable_provider() -> None:
    service = OCRService(providers=[NoisyProvider(), ReadableProvider()])

    result = service.recognize(ImageInput(image_bytes=b"fake"), options={"selection_mode": "quality"})

    assert result.provider == "rapidocr"
    assert result.full_text == "Apifox 登录页 正在等待扫码登录"
    assert result.raw is not None
    assert result.raw["selected_by"] == "quality_score"
    candidates = result.raw["provider_candidates"]
    assert [candidate["provider"] for candidate in candidates] == ["vision", "rapidocr"]
    assert candidates[1]["quality_score"] > candidates[0]["quality_score"]
