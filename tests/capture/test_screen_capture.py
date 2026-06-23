from ayes.capture.screen import MacOSScreenCapture
from ayes.targets.models import Bounds, WindowCandidate, observability_from_flags


def test_capture_window_returns_unsupported_when_backend_unavailable() -> None:
    capture = MacOSScreenCapture()
    capture.is_available = False
    result = capture.capture_window(
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
        timestamp=1.0,
    )
    assert result.ok is False
    assert result.status == "unsupported"
