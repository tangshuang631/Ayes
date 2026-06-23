from ayes.ocr.models import ImageInput, OCRResult
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
