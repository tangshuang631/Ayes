from ayes.capture.screen import MacOSScreenCapture, WindowsScreenCapture, create_screen_capture
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


def test_windows_capture_returns_unsupported_when_backend_unavailable() -> None:
    capture = WindowsScreenCapture()
    capture.is_available = False

    result = capture.capture_main_display(timestamp=1.0)

    assert result.ok is False
    assert result.status == "unsupported"


def test_create_screen_capture_returns_platform_backend() -> None:
    assert create_screen_capture(platform_name="darwin").__class__.__name__ == "MacOSScreenCapture"
    assert create_screen_capture(platform_name="win32").__class__.__name__ == "WindowsScreenCapture"
