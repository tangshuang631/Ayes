from pathlib import Path


def test_status_section_uses_raw_status_layout_without_health_summary_grid() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="statusSummary"' not in html
    assert 'id="statusRawSummary"' in html
    assert 'id="healthSummary"' not in html


def test_screenshot_preview_section_includes_overlay_and_meta() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="screenshotMeta"' in html
    assert 'id="screenshotOverlay"' in html
