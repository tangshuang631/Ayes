from ayes.observation.text_quality import score_ocr_text


def test_score_ocr_text_penalizes_diagnostic_and_symbolic_noise() -> None:
    noisy = score_ocr_text("Qwm*_SummaryffSf*A8 OCR vision | 字符 68 | 块 7", avg_confidence=0.58)

    assert noisy.score < 0.62
    assert noisy.is_noisy is True


def test_score_ocr_text_keeps_readable_main_content_high_quality() -> None:
    readable = score_ocr_text("Codex 正在编辑 Ayes OCR 抗噪优化", avg_confidence=0.58)

    assert readable.score > 0.7
    assert readable.is_noisy is False
