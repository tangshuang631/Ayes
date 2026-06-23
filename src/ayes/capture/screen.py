"""Minimal capture implementation for macOS."""

from __future__ import annotations

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
