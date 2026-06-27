"""Diff detection structures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiffStats:
    changed_pixels: int
    total_pixels: int
    change_ratio: float
    changed: bool
