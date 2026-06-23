from ayes.capture.ticker import SamplingTicker


def test_sampling_ticker_fires_on_first_tick_and_respects_intervals() -> None:
    ticker = SamplingTicker(
        screenshot_interval_ms=1000,
        ocr_interval_ms=2000,
        change_detection_interval_ms=500,
    )
    assert ticker.should_capture(0) is True
    assert ticker.should_run_ocr(0) is True
    assert ticker.should_run_diff(0) is True

    ticker.mark_capture(0)
    ticker.mark_ocr(0)
    ticker.mark_diff(0)

    assert ticker.should_capture(999) is False
    assert ticker.should_capture(1000) is True
    assert ticker.should_run_ocr(1999) is False
    assert ticker.should_run_ocr(2000) is True
    assert ticker.should_run_diff(499) is False
    assert ticker.should_run_diff(500) is True
