"""Shared local-time formatting helpers for user-visible Ayes output."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")


def format_local_clock(timestamp: Any) -> str:
    if timestamp in {None, ""}:
        return ""
    try:
        numeric = float(timestamp)
    except (TypeError, ValueError):
        return str(timestamp)
    return datetime.fromtimestamp(numeric, tz=DEFAULT_DISPLAY_TIMEZONE).strftime("%H:%M:%S")

