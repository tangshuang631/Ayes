"""Watch spec configuration contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ConfigError(ValueError):
    """Raised when watch spec validation fails."""


def _require_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{field_name} 必须是布尔值")


def _require_int(value: Any, field_name: str, minimum: Optional[int] = None) -> int:
    if not isinstance(value, int):
        raise ConfigError(f"{field_name} 必须是整数")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{field_name} 必须大于等于 {minimum}")
    return value


def _require_float(value: Any, field_name: str) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise ConfigError(f"{field_name} 必须是数字")


def _require_str(value: Any, field_name: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    raise ConfigError(f"{field_name} 必须是非空字符串")


@dataclass(frozen=True)
class WatchTarget:
    type: str
    process_name: Optional[str] = None
    process_id: Optional[int] = None
    window_id: Optional[int] = None
    screen_id: Optional[int] = None
    include_all_windows: bool = True
    only_observable_windows: bool = True
    regions: List["TargetRegion"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WatchTarget":
        target_type = _require_str(data.get("type"), "target.type")
        if target_type not in {"process", "window", "screen"}:
            raise ConfigError("target.type 必须是 process、window 或 screen")
        process_name = data.get("process_name")
        process_id = data.get("process_id")
        window_id = data.get("window_id")
        screen_id = data.get("screen_id")
        if target_type == "process" and process_name is None and process_id is None:
            raise ConfigError("process 目标至少需要 process_name 或 process_id")
        if target_type == "window" and window_id is None:
            raise ConfigError("window 目标必须提供 window_id")
        if target_type == "screen" and screen_id is None:
            raise ConfigError("screen 目标必须提供 screen_id")
        return cls(
            type=target_type,
            process_name=process_name,
            process_id=process_id,
            window_id=window_id,
            screen_id=screen_id,
            include_all_windows=_require_bool(data.get("include_all_windows", True), "target.include_all_windows"),
            only_observable_windows=_require_bool(
                data.get("only_observable_windows", True),
                "target.only_observable_windows",
            ),
            regions=[TargetRegion.from_dict(item) for item in data.get("regions", [])],
        )


@dataclass(frozen=True)
class TargetRegion:
    region_id: str
    name: str
    x: int
    y: int
    w: int
    h: int
    coordinate_space: str = "target"
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TargetRegion":
        coordinate_space = _require_str(data.get("coordinate_space", "target"), "target.regions[].coordinate_space")
        if coordinate_space not in {"target", "screen", "window"}:
            raise ConfigError("target.regions[].coordinate_space 必须是 target、screen 或 window")
        return cls(
            region_id=_require_str(data.get("region_id"), "target.regions[].region_id"),
            name=_require_str(data.get("name"), "target.regions[].name"),
            x=_require_int(data.get("x"), "target.regions[].x", 0),
            y=_require_int(data.get("y"), "target.regions[].y", 0),
            w=_require_int(data.get("w"), "target.regions[].w", 1),
            h=_require_int(data.get("h"), "target.regions[].h", 1),
            coordinate_space=coordinate_space,
            enabled=_require_bool(data.get("enabled", True), "target.regions[].enabled"),
        )


@dataclass(frozen=True)
class SamplingConfig:
    screenshot_interval_ms: int = 1000
    ocr_interval_ms: int = 1000
    change_detection_interval_ms: int = 1000
    max_fps: int = 2
    skip_ocr_when_no_change: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SamplingConfig":
        return cls(
            screenshot_interval_ms=_require_int(data.get("screenshot_interval_ms", 1000), "sampling.screenshot_interval_ms", 1),
            ocr_interval_ms=_require_int(data.get("ocr_interval_ms", 1000), "sampling.ocr_interval_ms", 1),
            change_detection_interval_ms=_require_int(
                data.get("change_detection_interval_ms", 1000),
                "sampling.change_detection_interval_ms",
                1,
            ),
            max_fps=_require_int(data.get("max_fps", 2), "sampling.max_fps", 1),
            skip_ocr_when_no_change=_require_bool(
                data.get("skip_ocr_when_no_change", True),
                "sampling.skip_ocr_when_no_change",
            ),
        )


@dataclass(frozen=True)
class VisionConfig:
    enabled: bool = False
    provider: str = "ollama"
    model: str = "Molmo-7B-D-0924"
    trigger_when_ocr_sparse: bool = True
    ocr_sparse_min_chars: int = 12
    trigger_on_visual_regions: bool = True
    trigger_on_watch_intent: bool = True
    trigger_on_question_semantics: bool = True
    max_calls_per_minute: int = 6

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisionConfig":
        provider = _require_str(data.get("provider", "ollama"), "vision.provider")
        return cls(
            enabled=_require_bool(data.get("enabled", False), "vision.enabled"),
            provider=provider,
            model=_require_str(data.get("model", "Molmo-7B-D-0924"), "vision.model"),
            trigger_when_ocr_sparse=_require_bool(
                data.get("trigger_when_ocr_sparse", True),
                "vision.trigger_when_ocr_sparse",
            ),
            ocr_sparse_min_chars=_require_int(data.get("ocr_sparse_min_chars", 12), "vision.ocr_sparse_min_chars", 0),
            trigger_on_visual_regions=_require_bool(
                data.get("trigger_on_visual_regions", True),
                "vision.trigger_on_visual_regions",
            ),
            trigger_on_watch_intent=_require_bool(
                data.get("trigger_on_watch_intent", True),
                "vision.trigger_on_watch_intent",
            ),
            trigger_on_question_semantics=_require_bool(
                data.get("trigger_on_question_semantics", True),
                "vision.trigger_on_question_semantics",
            ),
            max_calls_per_minute=_require_int(data.get("max_calls_per_minute", 6), "vision.max_calls_per_minute", 1),
        )


@dataclass(frozen=True)
class ShortTermMemoryConfig:
    enabled: bool = True
    retain_minutes: int = 15
    detail_level: str = "high"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShortTermMemoryConfig":
        retain_minutes = _require_int(data.get("retain_minutes", 15), "memory.short_term.retain_minutes", 1)
        if retain_minutes > 15:
            raise ConfigError("memory.short_term.retain_minutes 不能超过 15")
        return cls(
            enabled=_require_bool(data.get("enabled", True), "memory.short_term.enabled"),
            retain_minutes=retain_minutes,
            detail_level=_require_str(data.get("detail_level", "high"), "memory.short_term.detail_level"),
        )


@dataclass(frozen=True)
class LongTermMemoryConfig:
    enabled: bool = True
    retain_hours: int = 24
    max_retain_hours: int = 72
    summary_interval_minutes: int = 5
    detail_level: str = "summary"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LongTermMemoryConfig":
        retain_hours = _require_int(data.get("retain_hours", 24), "memory.long_term.retain_hours", 1)
        max_retain_hours = _require_int(data.get("max_retain_hours", 72), "memory.long_term.max_retain_hours", 1)
        if max_retain_hours > 72:
            raise ConfigError("memory.long_term.max_retain_hours 不能超过 72")
        if retain_hours > max_retain_hours:
            raise ConfigError("memory.long_term.retain_hours 不能超过 max_retain_hours")
        return cls(
            enabled=_require_bool(data.get("enabled", True), "memory.long_term.enabled"),
            retain_hours=retain_hours,
            max_retain_hours=max_retain_hours,
            summary_interval_minutes=_require_int(
                data.get("summary_interval_minutes", 5),
                "memory.long_term.summary_interval_minutes",
                1,
            ),
            detail_level=_require_str(data.get("detail_level", "summary"), "memory.long_term.detail_level"),
        )


@dataclass(frozen=True)
class MemoryConfig:
    short_term: ShortTermMemoryConfig = field(default_factory=ShortTermMemoryConfig)
    long_term: LongTermMemoryConfig = field(default_factory=LongTermMemoryConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryConfig":
        return cls(
            short_term=ShortTermMemoryConfig.from_dict(data.get("short_term", {})),
            long_term=LongTermMemoryConfig.from_dict(data.get("long_term", {})),
        )


@dataclass(frozen=True)
class WatchRule:
    type: str
    any: List[str] = field(default_factory=list)
    field: Optional[str] = None
    operator: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WatchRule":
        rule_type = _require_str(data.get("type"), "watch_intent.rules[].type")
        if rule_type == "text_contains":
            any_values = data.get("any", [])
            if not isinstance(any_values, list) or not any(isinstance(item, str) and item.strip() for item in any_values):
                raise ConfigError("text_contains 规则必须提供非空 any 字符串列表")
            return cls(type=rule_type, any=[item.strip() for item in any_values if item.strip()])
        if rule_type == "numeric_threshold":
            operator = _require_str(data.get("operator"), "watch_intent.rules[].operator")
            if operator not in {"lt", "lte", "gt", "gte", "eq"}:
                raise ConfigError("numeric_threshold.operator 不合法")
            return cls(
                type=rule_type,
                field=_require_str(data.get("field"), "watch_intent.rules[].field"),
                operator=operator,
                value=_require_float(data.get("value"), "watch_intent.rules[].value"),
                unit=data.get("unit"),
            )
        raise ConfigError("暂不支持的 watch_intent 规则类型")


@dataclass(frozen=True)
class SemanticMatchConfig:
    enabled: bool = True
    threshold: float = 0.78

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SemanticMatchConfig":
        threshold = _require_float(data.get("threshold", 0.78), "watch_intent.semantic_match.threshold")
        if not 0 <= threshold <= 1:
            raise ConfigError("watch_intent.semantic_match.threshold 必须在 0 到 1 之间")
        return cls(
            enabled=_require_bool(data.get("enabled", True), "watch_intent.semantic_match.enabled"),
            threshold=threshold,
        )


@dataclass(frozen=True)
class WatchIntentConfig:
    enabled: bool
    summary: str
    queries: List[str] = field(default_factory=list)
    rules: List[WatchRule] = field(default_factory=list)
    semantic_match: SemanticMatchConfig = field(default_factory=SemanticMatchConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, mode: str) -> "WatchIntentConfig":
        enabled = _require_bool(data.get("enabled", mode == "triggered"), "watch_intent.enabled")
        summary = data.get("summary", "")
        if mode == "triggered" and not enabled:
            raise ConfigError("triggered 模式必须启用 watch_intent")
        if enabled and not isinstance(summary, str):
            raise ConfigError("watch_intent.summary 必须是字符串")
        queries = data.get("queries", [])
        if not isinstance(queries, list):
            raise ConfigError("watch_intent.queries 必须是列表")
        rules = [WatchRule.from_dict(item) for item in data.get("rules", [])]
        return cls(
            enabled=enabled,
            summary=summary.strip(),
            queries=[item.strip() for item in queries if isinstance(item, str) and item.strip()],
            rules=rules,
            semantic_match=SemanticMatchConfig.from_dict(data.get("semantic_match", {})),
        )


@dataclass(frozen=True)
class AlertConfig:
    enabled: bool = False
    channel: str = "wecom_webhook"
    webhook_url_env: str = "AYES_WECOM_WEBHOOK_URL"
    webhook_url: str = ""
    priority_threshold: str = "medium"
    cooldown_sec: int = 120
    dedupe_window_sec: int = 300

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlertConfig":
        priority_threshold = _require_str(data.get("priority_threshold", "medium"), "alert.priority_threshold")
        if priority_threshold not in {"low", "medium", "high"}:
            raise ConfigError("alert.priority_threshold 必须是 low、medium 或 high")
        raw_webhook_url = data.get("webhook_url", "")
        if raw_webhook_url is None:
            webhook_url = ""
        elif isinstance(raw_webhook_url, str):
            webhook_url = raw_webhook_url.strip()
        else:
            raise ConfigError("alert.webhook_url 必须是字符串")
        return cls(
            enabled=_require_bool(data.get("enabled", False), "alert.enabled"),
            channel=_require_str(data.get("channel", "wecom_webhook"), "alert.channel"),
            webhook_url_env=_require_str(data.get("webhook_url_env", "AYES_WECOM_WEBHOOK_URL"), "alert.webhook_url_env"),
            webhook_url=webhook_url,
            priority_threshold=priority_threshold,
            cooldown_sec=_require_int(data.get("cooldown_sec", 120), "alert.cooldown_sec", 0),
            dedupe_window_sec=_require_int(data.get("dedupe_window_sec", 300), "alert.dedupe_window_sec", 0),
        )


@dataclass(frozen=True)
class ClickPoint:
    x: int
    y: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClickPoint":
        return cls(
            x=_require_int(data.get("x"), "actions.refresh_click.point.x"),
            y=_require_int(data.get("y"), "actions.refresh_click.point.y"),
        )


@dataclass(frozen=True)
class RefreshClickConfig:
    enabled: bool = False
    point: Optional[ClickPoint] = None
    coordinate_space: str = "window"
    interval_sec: int = 30
    cooldown_sec: int = 30
    max_clicks_per_hour: int = 120
    pause_when_target_matched: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RefreshClickConfig":
        enabled = _require_bool(data.get("enabled", False), "actions.refresh_click.enabled")
        point_data = data.get("point")
        point = ClickPoint.from_dict(point_data) if point_data is not None else None
        coordinate_space = _require_str(data.get("coordinate_space", "window"), "actions.refresh_click.coordinate_space")
        if coordinate_space not in {"window", "screen"}:
            raise ConfigError("actions.refresh_click.coordinate_space 必须是 window 或 screen")
        if enabled and point is None:
            raise ConfigError("启用 refresh_click 时必须提供 point")
        return cls(
            enabled=enabled,
            point=point,
            coordinate_space=coordinate_space,
            interval_sec=_require_int(data.get("interval_sec", 30), "actions.refresh_click.interval_sec", 1),
            cooldown_sec=_require_int(data.get("cooldown_sec", 30), "actions.refresh_click.cooldown_sec", 0),
            max_clicks_per_hour=_require_int(
                data.get("max_clicks_per_hour", 120),
                "actions.refresh_click.max_clicks_per_hour",
                1,
            ),
            pause_when_target_matched=_require_bool(
                data.get("pause_when_target_matched", True),
                "actions.refresh_click.pause_when_target_matched",
            ),
        )


@dataclass(frozen=True)
class ActionsConfig:
    refresh_click: RefreshClickConfig = field(default_factory=RefreshClickConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionsConfig":
        return cls(refresh_click=RefreshClickConfig.from_dict(data.get("refresh_click", {})))


@dataclass(frozen=True)
class WatchSpec:
    spec_version: str
    mode: str
    target: WatchTarget
    sampling: SamplingConfig
    vision: VisionConfig
    memory: MemoryConfig
    watch_intent: WatchIntentConfig
    alert: AlertConfig
    actions: ActionsConfig

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WatchSpec":
        spec_version = _require_str(data.get("spec_version", "1.0"), "spec_version")
        mode = _require_str(data.get("mode"), "mode")
        if mode not in {"triggered", "observe"}:
            raise ConfigError("mode 必须是 triggered 或 observe")
        return cls(
            spec_version=spec_version,
            mode=mode,
            target=WatchTarget.from_dict(data.get("target", {})),
            sampling=SamplingConfig.from_dict(data.get("sampling", {})),
            vision=VisionConfig.from_dict(data.get("vision", {})),
            memory=MemoryConfig.from_dict(data.get("memory", {})),
            watch_intent=WatchIntentConfig.from_dict(data.get("watch_intent", {}), mode=mode),
            alert=AlertConfig.from_dict(data.get("alert", {})),
            actions=ActionsConfig.from_dict(data.get("actions", {})),
        )
