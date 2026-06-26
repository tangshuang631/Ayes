"""Attention windows for whole-target monitoring without explicit ROI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ayes.config.models import TargetRegion


@dataclass(frozen=True)
class AttentionRegion:
    region: TargetRegion
    weight: float
    role: str
    reason: str
    primary: bool = False


def build_default_attention_regions(*, width: int, height: int) -> List[AttentionRegion]:
    """Create deterministic screen-layout regions when users did not bind ROI."""
    safe_width = max(int(width or 0), 1)
    safe_height = max(int(height or 0), 1)
    center_x = int(safe_width * 0.18)
    center_y = int(safe_height * 0.16)
    center_w = max(int(safe_width * 0.64), 1)
    center_h = max(int(safe_height * 0.68), 1)
    top_h = max(int(safe_height * 0.18), 1)
    bottom_h = max(int(safe_height * 0.16), 1)
    side_w = max(int(safe_width * 0.24), 1)
    regions = [
        AttentionRegion(
            region=TargetRegion(
                region_id="auto_center_main",
                name="自动主内容区",
                x=center_x,
                y=center_y,
                w=min(center_w, safe_width - center_x),
                h=min(center_h, safe_height - center_y),
            ),
            weight=1.0,
            role="main_content",
            reason="无 ROI 时优先观察屏幕或窗口中间主内容，避免边角状态文字抢占摘要。",
            primary=True,
        ),
        AttentionRegion(
            region=TargetRegion(region_id="auto_full", name="自动全目标", x=0, y=0, w=safe_width, h=safe_height),
            weight=0.72,
            role="full_context",
            reason="保留完整目标上下文，供证据回溯和低频整体理解使用。",
        ),
        AttentionRegion(
            region=TargetRegion(region_id="auto_top_bar", name="自动顶部栏", x=0, y=0, w=safe_width, h=top_h),
            weight=0.38,
            role="chrome_or_navigation",
            reason="顶部栏通常包含标题、地址、标签页或导航信息，权重低于主内容。",
        ),
        AttentionRegion(
            region=TargetRegion(region_id="auto_left_panel", name="自动左侧栏", x=0, y=top_h, w=side_w, h=max(safe_height - top_h - bottom_h, 1)),
            weight=0.34,
            role="sidebar",
            reason="左侧栏常见于导航列表，默认只作为辅助上下文。",
        ),
        AttentionRegion(
            region=TargetRegion(
                region_id="auto_right_panel",
                name="自动右侧栏",
                x=max(safe_width - side_w, 0),
                y=top_h,
                w=side_w,
                h=max(safe_height - top_h - bottom_h, 1),
            ),
            weight=0.32,
            role="side_context",
            reason="右侧栏或浮层作为辅助上下文，默认不覆盖中心主内容。",
        ),
        AttentionRegion(
            region=TargetRegion(
                region_id="auto_bottom_bar",
                name="自动底部栏",
                x=0,
                y=max(safe_height - bottom_h, 0),
                w=safe_width,
                h=bottom_h,
            ),
            weight=0.28,
            role="status_or_footer",
            reason="底部状态栏、dock 或页脚信息默认低权重处理。",
        ),
    ]
    return regions

