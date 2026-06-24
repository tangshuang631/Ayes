from pathlib import Path


def test_status_section_uses_raw_status_layout_without_health_summary_grid() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="statusSummary"' not in html
    assert 'id="statusRawSummary"' in html
    assert 'id="healthSummary"' not in html
