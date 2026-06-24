from pathlib import Path


def test_status_section_uses_raw_status_layout_without_health_summary_grid() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="statusSummary"' not in html
    assert 'id="statusRawSummary"' in html
    assert 'id="healthSummary"' not in html
    assert 'id="runtimeMeta"' in html


def test_screenshot_preview_section_includes_overlay_and_meta() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="screenshotMeta"' in html
    assert 'id="screenshotOverlay"' in html


def test_workbench_still_exposes_selected_target_summary_anchor() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="selectedTargetSummary"' in html


def test_memory_panel_exposes_quick_question_anchors() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="memoryQuickQuestions"' in html


def test_memory_panel_exposes_context_summary_anchor() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="memoryContextSummary"' in html


def test_memory_panel_exposes_screenshot_reference_anchor() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="memoryScreenshotReference"' in html


def test_memory_panel_exposes_follow_up_question_anchor() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="memoryFollowupQuestions"' in html


def test_memory_panel_exposes_evidence_summary_anchor() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="memoryEvidenceSummary"' in html
