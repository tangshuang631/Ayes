"""Capture feasibility matrix helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from ayes.capture.models import CaptureResult
from ayes.targets.models import WindowCandidate


@dataclass(frozen=True)
class CaptureFeasibilityRow:
    process_name: str
    window_id: int
    title: str
    observable_state: str
    has_pixels: bool
    is_onscreen: bool
    expected_capture_result: str
    actual_capture_status: str = "not_tested"
    actual_capture_ok: bool = False


def build_capture_feasibility_rows(
    candidates: Iterable[WindowCandidate],
    *,
    capture_results: dict[int, CaptureResult] | None = None,
) -> List[CaptureFeasibilityRow]:
    rows: List[CaptureFeasibilityRow] = []
    for candidate in candidates:
        if candidate.observability.code == "observable":
            expected = "recommended"
        elif candidate.observability.code == "partial":
            expected = "best_effort"
        else:
            expected = "metadata_only"
        result = capture_results.get(candidate.window_id) if capture_results else None
        rows.append(
            CaptureFeasibilityRow(
                process_name=candidate.process_name,
                window_id=candidate.window_id,
                title=candidate.title,
                observable_state=candidate.observability.label,
                has_pixels=candidate.observability.has_pixels,
                is_onscreen=candidate.is_onscreen,
                expected_capture_result=expected,
                actual_capture_status=result.status if result else "not_tested",
                actual_capture_ok=result.ok if result else False,
            )
        )
    return rows
