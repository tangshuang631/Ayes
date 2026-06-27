from ayes.capture.models import CaptureResult
from ayes.targets.capture_matrix import build_capture_feasibility_rows
from ayes.targets.models import Bounds, WindowCandidate, observability_from_flags


def test_capture_feasibility_rows_follow_observability() -> None:
    candidates = [
        WindowCandidate(
            window_id=1,
            process_id=100,
            process_name="MainApp",
            title="主窗口",
            bounds=Bounds(x=0, y=0, width=800, height=600),
            layer=0,
            is_onscreen=True,
            observability=observability_from_flags(has_pixels=True, is_onscreen=True),
            is_business_candidate=True,
        ),
        WindowCandidate(
            window_id=2,
            process_id=100,
            process_name="MainApp",
            title="后台窗口",
            bounds=Bounds(x=0, y=0, width=800, height=600),
            layer=0,
            is_onscreen=False,
            observability=observability_from_flags(has_pixels=True, is_onscreen=False),
            is_business_candidate=True,
        ),
        WindowCandidate(
            window_id=3,
            process_id=100,
            process_name="MainApp",
            title="辅助窗口",
            bounds=Bounds(x=0, y=0, width=100, height=80),
            layer=1,
            is_onscreen=False,
            observability=observability_from_flags(has_pixels=False, is_onscreen=False),
            is_business_candidate=False,
        ),
    ]
    rows = build_capture_feasibility_rows(
        candidates,
        capture_results={
            1: CaptureResult(ok=True, status="ok"),
            2: CaptureResult(ok=False, status="no_pixels"),
            3: CaptureResult(ok=False, status="unsupported"),
        },
    )
    assert rows[0].expected_capture_result == "recommended"
    assert rows[1].expected_capture_result == "best_effort"
    assert rows[2].expected_capture_result == "metadata_only"
    assert rows[0].actual_capture_status == "ok"
    assert rows[1].actual_capture_ok is False
