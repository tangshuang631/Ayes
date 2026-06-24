"""Serializable planning payloads for watch-spec orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class PlanIssue:
    field: str
    reason: str


@dataclass(frozen=True)
class WatchPlanDraft:
    plan_version: str
    task_id: str
    user_prompt: str
    draft_spec: Dict[str, Any]
    mode: str
    intent_category: str
    target_hint: Dict[str, Any] = field(default_factory=dict)
    resolved_target: Dict[str, Any] = field(default_factory=dict)
    missing_fields: List[PlanIssue] = field(default_factory=list)
    ambiguities: List[PlanIssue] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    confirmation_summary: List[str] = field(default_factory=list)
    can_apply_directly: bool = False
    status: str = "needs_confirmation"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
