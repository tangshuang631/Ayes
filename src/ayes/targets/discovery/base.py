"""Discovery interfaces."""

from __future__ import annotations

from typing import Iterable, Protocol

from ayes.targets.models import WindowCandidate


class WindowDiscovery(Protocol):
    def list_windows(self) -> Iterable[WindowCandidate]:
        """Return discoverable window candidates."""
