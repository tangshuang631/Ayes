"""Platform-specific target discovery backend factory."""

from __future__ import annotations

import sys

from ayes.targets.discovery.macos import MacOSWindowDiscovery
from ayes.targets.discovery.windows import WindowsWindowDiscovery


def create_window_discovery(*, platform_name: str | None = None):
    platform = (platform_name or sys.platform).lower()
    if platform.startswith("win"):
        return WindowsWindowDiscovery()
    return MacOSWindowDiscovery()
