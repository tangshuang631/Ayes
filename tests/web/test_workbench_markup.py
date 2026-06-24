from pathlib import Path


def test_status_section_uses_raw_status_layout_without_health_summary_grid() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="statusSummary"' not in html
    assert 'id="statusRawSummary"' in html
    assert 'id="healthSummary"' not in html
    assert 'id="runtimeMeta"' in html
    assert 'id="statusRecentBlocks"' in html
    assert 'id="statusEvidencePreview"' in html


def test_screenshot_preview_section_includes_overlay_and_meta() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="screenshotMeta"' in html
    assert 'id="screenshotOverlay"' in html
    assert 'id="screenshotPreview"' in html


def test_workbench_exposes_shared_evidence_inspector_anchors() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="selectedEvidenceMeta"' in html
    assert 'id="selectedEvidenceSummary"' in html
    assert 'id="selectedEvidencePreview"' in html


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


def test_workbench_exposes_agent_entry_anchors() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="agentEntrySummary"' in html
    assert 'id="agentContractsBtn"' in html
    assert 'id="agentContractsView"' in html


def test_workbench_exposes_getting_started_flow_anchors() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="gettingStartedGuide"' in html
    assert 'id="gettingStartedStepTarget"' in html
    assert 'id="gettingStartedStepConfig"' in html
    assert 'id="gettingStartedStepRun"' in html
    assert 'id="gettingStartedStepAsk"' in html


def test_task_scope_section_is_folded_by_default() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="taskScopeSection"' in html
    assert "<summary>任务与时间范围</summary>" in html


def test_low_frequency_panels_are_grouped_under_collapsed_sections() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="collapsedOcrSection"' in html
    assert 'id="collapsedTraceSection"' in html
    assert 'id="collapsedLongTermSection"' in html
    assert 'id="collapsedLogSection"' in html
    assert "<summary>更多 OCR 与轨迹</summary>" in html
    assert "<summary>长期摘要与日志</summary>" in html


def test_roi_editor_anchors_remain_available_for_target_switch_reset_flow() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="roiEditorEmpty"' in html
    assert 'id="roiEditorShell"' in html
    assert 'id="roiEditorImage"' in html
    assert 'id="regionsJsonInput"' in html
    assert 'id="modeSelect"' in html
    assert 'id="queryInput"' in html
    assert 'id="screenshotIntervalInput"' in html
    assert 'id="ocrIntervalInput"' in html
