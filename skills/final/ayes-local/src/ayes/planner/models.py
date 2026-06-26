"""Serializable planning payloads for watch-spec orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class PlanIssue:
    field: str
    reason: str


@dataclass(frozen=True)
class PlanQuestion:
    question_id: str
    kind: str
    field: str
    prompt: str
    required: bool = True
    suggested_answer: str = ""


@dataclass(frozen=True)
class RegionIntent:
    region_intent_id: str
    name: str
    purpose: str
    required: bool = True
    status: str = "needs_binding"


@dataclass(frozen=True)
class ActionIntent:
    action_type: str
    purpose: str
    required_confirmation: bool = True
    missing_fields: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SetupGuidance:
    guidance_id: str
    topic: str
    status: str
    summary: str
    blocking_fields: List[str] = field(default_factory=list)
    user_steps: List[str] = field(default_factory=list)
    agent_steps: List[str] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)
    can_agent_attempt_after_permission: bool = False


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
    questions: List[PlanQuestion] = field(default_factory=list)
    region_intents: List[RegionIntent] = field(default_factory=list)
    action_intents: List[ActionIntent] = field(default_factory=list)
    setup_guidance: List[SetupGuidance] = field(default_factory=list)
    ambiguities: List[PlanIssue] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    confirmation_summary: List[str] = field(default_factory=list)
    can_apply_directly: bool = False
    status: str = "needs_confirmation"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
