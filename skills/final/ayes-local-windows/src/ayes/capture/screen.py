"""Screen and window capture backends."""

from __future__ import annotations

import sys
from io import BytesIO
from uuid import uuid4

from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.targets.models import WindowCandidate

try:
    import Quartz  # type: ignore
    from AppKit import NSBitmapImageRep, NSPNGFileType  # type: ignore
except ImportError:  # pragma: no cover
    Quartz = None
    NSBitmapImageRep = None
    NSPNGFileType = None

try:
    import mss  # type: ignore
except ImportError:  # pragma: no cover
    mss = None

try:
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover
    Image = None


class MacOSScreenCapture:
    def __init__(self) -> None:
        self.is_available = Quartz is not None and NSBitmapImageRep is not None

    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        if not self.is_available:
            return CaptureResult(ok=False, status="unsupported", message="Quartz/AppKit 不可用")
        image = Quartz.CGDisplayCreateImage(Quartz.CGMainDisplayID())
        if image is None:
            return CaptureResult(ok=False, status="failed", message="无法创建主屏截图")
        return self._build_result(image=image, timestamp=timestamp, target_type="screen", target_id="main")

    def capture_window(self, candidate: WindowCandidate, *, timestamp: float) -> CaptureResult:
        if not self.is_available:
            return CaptureResult(ok=False, status="unsupported", message="Quartz/AppKit 不可用")
        image = Quartz.CGWindowListCreateImage(
            Quartz.CGRectNull,
            Quartz.kCGWindowListOptionIncludingWindow,
            candidate.window_id,
            Quartz.kCGWindowImageBoundsIgnoreFraming,
        )
        if image is None:
            return CaptureResult(
                ok=False,
                status="no_pixels",
                message=f"窗口 {candidate.window_id} 无法生成图像",
            )
        return self._build_result(
            image=image,
            timestamp=timestamp,
            target_type="window",
            target_id=str(candidate.window_id),
        )

    def _build_result(self, *, image: object, timestamp: float, target_type: str, target_id: str) -> CaptureResult:
        width = Quartz.CGImageGetWidth(image)
        height = Quartz.CGImageGetHeight(image)
        bitmap = NSBitmapImageRep.alloc().initWithCGImage_(image)
        png_data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
        if png_data is None:
            return CaptureResult(ok=False, status="failed", message="截图编码失败")
        image_bytes = bytes(png_data)
        frame = CaptureFrame(
            frame_id=f"frame_{uuid4().hex}",
            timestamp=timestamp,
            target_type=target_type,
            target_id=target_id,
            width=int(width),
            height=int(height),
            image_bytes=image_bytes,
            metadata={"image_format": "png"},
        )
        return CaptureResult(ok=True, status="ok", frame=frame)


class WindowsScreenCapture:
    """Best-effort Windows capture using mss and window-bounds cropping."""

    def __init__(self) -> None:
        self.is_available = mss is not None and Image is not None

    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        if not self.is_available:
            return CaptureResult(ok=False, status="unsupported", message="mss/Pillow 不可用")
        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            raw = sct.grab(monitor)
            image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return self._build_result(image=image, timestamp=timestamp, target_type="screen", target_id="main", metadata={"capture_backend": "mss"})

    def capture_window(self, candidate: WindowCandidate, *, timestamp: float) -> CaptureResult:
        if not self.is_available:
            return CaptureResult(ok=False, status="unsupported", message="mss/Pillow 不可用")
        if candidate.bounds.width <= 0 or candidate.bounds.height <= 0:
            return CaptureResult(ok=False, status="no_pixels", message=f"窗口 {candidate.window_id} 无有效边界")
        with mss.mss() as sct:
            raw = sct.grab(
                {
                    "left": candidate.bounds.x,
                    "top": candidate.bounds.y,
                    "width": candidate.bounds.width,
                    "height": candidate.bounds.height,
                }
            )
            image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return self._build_result(
            image=image,
            timestamp=timestamp,
            target_type="window",
            target_id=str(candidate.window_id),
            metadata={"capture_backend": "mss_window_crop"},
        )

    def _build_result(self, *, image: object, timestamp: float, target_type: str, target_id: str, metadata: dict) -> CaptureResult:
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        width, height = image.size
        frame = CaptureFrame(
            frame_id=f"frame_{uuid4().hex}",
            timestamp=timestamp,
            target_type=target_type,
            target_id=target_id,
            width=int(width),
            height=int(height),
            image_bytes=buffer.getvalue(),
            metadata={"image_format": "png", **metadata},
        )
        return CaptureResult(ok=True, status="ok", frame=frame)


def create_screen_capture(*, platform_name: str | None = None):
    platform = (platform_name or sys.platform).lower()
    if platform.startswith("win"):
        return WindowsScreenCapture()
    return MacOSScreenCapture()
