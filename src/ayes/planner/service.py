"""Heuristic planner from natural language to watch-spec drafts."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from ayes.config.models import WatchSpec
from ayes.planner.models import PlanIssue, WatchPlanDraft


class WatchSpecPlanner:
    def plan(
        self,
        *,
        task_id: str,
        prompt: str,
        target: Optional[Dict[str, Any]] = None,
        webhook_url: Optional[str] = None,
    ) -> WatchPlanDraft:
        cleaned_prompt = " ".join(str(prompt or "").split())
        if not cleaned_prompt:
            raise ValueError("prompt 不能为空")
        mode = self._infer_mode(cleaned_prompt, webhook_url=webhook_url)
        intent_category = self._infer_intent_category(cleaned_prompt)
        draft_spec = self._build_default_spec(mode=mode)
        missing_fields: List[PlanIssue] = []
        ambiguities: List[PlanIssue] = []
        assumptions: List[str] = []
        confirmation_summary: List[str] = []

        resolved_target = self._normalize_target(target or {})
        if resolved_target:
            draft_spec["target"] = resolved_target
            confirmation_summary.append(self._build_target_summary(resolved_target))
        else:
            missing_fields.append(PlanIssue(field="target", reason="尚未指定监控目标"))

        watch_intent, watch_assumptions = self._build_watch_intent(cleaned_prompt, mode=mode)
        assumptions.extend(watch_assumptions)
        draft_spec["watch_intent"] = watch_intent

        sampling, sampling_assumptions = self._build_sampling(cleaned_prompt)
        assumptions.extend(sampling_assumptions)
        draft_spec["sampling"] = sampling

        memory, memory_assumptions = self._build_memory(cleaned_prompt)
        assumptions.extend(memory_assumptions)
        draft_spec["memory"] = memory

        vision, vision_assumptions = self._build_vision(cleaned_prompt)
        assumptions.extend(vision_assumptions)
        draft_spec["vision"] = vision

        alert = self._build_alert(mode=mode, webhook_url=webhook_url)
        draft_spec["alert"] = alert
        if mode == "triggered" and not alert.get("webhook_url"):
            missing_fields.append(PlanIssue(field="alert.webhook_url", reason="triggered 模式需要可用通知出口"))
        if mode == "triggered":
            confirmation_summary.append(self._build_trigger_summary(watch_intent))
        else:
            confirmation_summary.append("将持续保留近期事件、记忆与可回放证据，不主动发送告警")

        refresh_click, refresh_issues, refresh_assumptions = self._build_refresh_click(cleaned_prompt)
        draft_spec["actions"] = {"refresh_click": refresh_click}
        missing_fields.extend(refresh_issues)
        assumptions.extend(refresh_assumptions)
        if refresh_click.get("enabled"):
            confirmation_summary.append("已识别到刷新诉求，但仍需确认刷新点击坐标")

        confirmation_summary.append(
            f"短期记忆保留 {draft_spec['memory']['short_term']['retain_minutes']} 分钟，"
            f"长期记忆保留 {draft_spec['memory']['long_term']['retain_hours']} 小时"
        )
        if draft_spec["vision"]["enabled"]:
            confirmation_summary.append(f"已建议开启视觉增强模型 {draft_spec['vision']['model']}")
        if not watch_intent.get("queries") and not watch_intent.get("rules") and mode == "triggered":
            ambiguities.append(PlanIssue(field="watch_intent", reason="未从自然语言中稳定提取出触发条件"))

        can_apply_directly = not missing_fields and not ambiguities and bool(resolved_target)
        return WatchPlanDraft(
            plan_version="1.0",
            task_id=task_id,
            user_prompt=cleaned_prompt,
            draft_spec=draft_spec,
            mode=mode,
            intent_category=intent_category,
            target_hint=target or {},
            resolved_target=resolved_target,
            missing_fields=missing_fields,
            ambiguities=ambiguities,
            assumptions=assumptions,
            confirmation_summary=confirmation_summary,
            can_apply_directly=can_apply_directly,
            status="ready" if can_apply_directly else "needs_confirmation",
        )

    def confirm(
        self,
        *,
        plan_payload: Dict[str, Any],
        confirmations: Optional[Dict[str, Any]] = None,
    ) -> Tuple[WatchSpec, Dict[str, Any]]:
        if not isinstance(plan_payload, dict) or not isinstance(plan_payload.get("draft_spec"), dict):
            raise ValueError("plan.draft_spec 缺失或不合法")
        payload = copy.deepcopy(plan_payload)
        spec_payload = copy.deepcopy(payload["draft_spec"])
        confirmations = confirmations or {}

        webhook_url = str(confirmations.get("webhook_url") or "").strip()
        if webhook_url:
            alert = spec_payload.setdefault("alert", {})
            alert["enabled"] = True
            alert["channel"] = "wecom_webhook"
            alert["webhook_url"] = webhook_url

        target_override = confirmations.get("target")
        if isinstance(target_override, dict) and target_override:
            spec_payload["target"] = self._normalize_target(target_override)

        regions = confirmations.get("regions")
        if isinstance(regions, list) and regions:
            spec_payload.setdefault("target", {})["regions"] = regions

        refresh_click_point = confirmations.get("refresh_click_point")
        if isinstance(refresh_click_point, dict) and refresh_click_point:
            refresh_click = spec_payload.setdefault("actions", {}).setdefault("refresh_click", {})
            refresh_click["enabled"] = True
            refresh_click["point"] = refresh_click_point
            refresh_click.setdefault("coordinate_space", "window")

        spec = WatchSpec.from_dict(spec_payload)
        payload["draft_spec"] = spec_payload
        payload["resolved_target"] = self._normalize_target(spec_payload.get("target") or {})
        payload["missing_fields"] = []
        payload["ambiguities"] = []
        payload["can_apply_directly"] = True
        payload["status"] = "ready"
        return spec, payload

    def _build_default_spec(self, *, mode: str) -> Dict[str, Any]:
        return {
            "spec_version": "1.0",
            "mode": mode,
            "target": {},
            "sampling": {
                "screenshot_interval_ms": 1000,
                "ocr_interval_ms": 1000,
                "change_detection_interval_ms": 1000,
                "max_fps": 2,
                "skip_ocr_when_no_change": True,
            },
            "vision": {
                "enabled": False,
                "provider": "ollama",
                "model": "Molmo-7B-D-0924",
                "trigger_when_ocr_sparse": True,
                "ocr_sparse_min_chars": 12,
                "trigger_on_visual_regions": True,
                "trigger_on_watch_intent": True,
                "trigger_on_question_semantics": True,
                "max_calls_per_minute": 6,
            },
            "memory": {
                "short_term": {
                    "enabled": True,
                    "retain_minutes": 15,
                    "detail_level": "high",
                },
                "long_term": {
                    "enabled": True,
                    "retain_hours": 24,
                    "max_retain_hours": 72,
                    "summary_interval_minutes": 5,
                    "detail_level": "summary",
                },
            },
            "watch_intent": {
                "enabled": mode == "triggered",
                "summary": "",
                "queries": [],
                "rules": [],
                "semantic_match": {"enabled": True, "threshold": 0.78},
            },
            "alert": {
                "enabled": mode == "triggered",
                "channel": "wecom_webhook",
                "webhook_url_env": "AYES_WECOM_WEBHOOK_URL",
                "webhook_url": "",
                "priority_threshold": "medium",
                "cooldown_sec": 120,
                "dedupe_window_sec": 300,
            },
            "actions": {
                "refresh_click": {
                    "enabled": False,
                    "coordinate_space": "window",
                    "interval_sec": 30,
                    "cooldown_sec": 30,
                    "max_clicks_per_hour": 120,
                    "pause_when_target_matched": True,
                }
            },
        }

    def _infer_mode(self, prompt: str, *, webhook_url: Optional[str]) -> str:
        if webhook_url:
            return "triggered"
        trigger_keywords = ["提醒", "通知", "告警", "有货", "低于", "高于", "弹窗报错", "出现错误", "价格"]
        if any(keyword in prompt for keyword in trigger_keywords):
            return "triggered"
        return "observe"

    def _infer_intent_category(self, prompt: str) -> str:
        if "价格" in prompt and any(token in prompt for token in ["低于", "高于", "大于", "小于"]):
            return "price_watch"
        if "有货" in prompt or "库存" in prompt:
            return "stock_watch"
        if "报错" in prompt or "错误" in prompt or "异常" in prompt:
            return "error_watch"
        return "general_observe"

    def _build_watch_intent(self, prompt: str, *, mode: str) -> Tuple[Dict[str, Any], List[str]]:
        assumptions: List[str] = []
        queries: List[str] = []
        rules: List[Dict[str, Any]] = []
        summary = prompt

        price_match = re.search(r"价格\s*(?:低于|小于|不高于)\s*([0-9]+(?:\.[0-9]+)?)", prompt)
        if price_match:
            value = float(price_match.group(1))
            queries.append(f"价格低于 {value:g}")
            rules.append(
                {
                    "type": "numeric_threshold",
                    "field": "price",
                    "operator": "lt",
                    "value": value,
                    "unit": "cny",
                }
            )
        price_match_gt = re.search(r"价格\s*(?:高于|大于|不低于)\s*([0-9]+(?:\.[0-9]+)?)", prompt)
        if price_match_gt:
            value = float(price_match_gt.group(1))
            queries.append(f"价格高于 {value:g}")
            rules.append(
                {
                    "type": "numeric_threshold",
                    "field": "price",
                    "operator": "gt",
                    "value": value,
                    "unit": "cny",
                }
            )

        stock_match = re.search(r"库存\s*(?:低于|小于|不高于)\s*([0-9]+(?:\.[0-9]+)?)", prompt)
        if stock_match:
            value = float(stock_match.group(1))
            queries.append(f"库存低于 {value:g}")
            rules.append(
                {
                    "type": "numeric_threshold",
                    "field": "stock",
                    "operator": "lt",
                    "value": value,
                    "unit": "count",
                }
            )

        if "有货" in prompt:
            queries.extend(["有货", "库存恢复", "立即购买"])
        if any(token in prompt for token in ["报错", "错误", "异常"]):
            queries.extend(["报错", "错误", "异常"])
        if "弹窗" in prompt:
            queries.append("弹窗")

        queries = self._dedupe_strs(queries)
        if mode == "observe":
            enabled = bool(queries or rules)
            if not queries and not rules:
                summary = ""
        else:
            enabled = True
            if not queries and not rules:
                queries = [prompt]
                assumptions.append("未识别出更细的触发条件，暂以原始请求作为监控查询")
        return {
            "enabled": enabled,
            "summary": summary,
            "queries": queries,
            "rules": rules,
            "semantic_match": {"enabled": True, "threshold": 0.78},
        }, assumptions

    def _build_sampling(self, prompt: str) -> Tuple[Dict[str, Any], List[str]]:
        sampling = {
            "screenshot_interval_ms": 1000,
            "ocr_interval_ms": 1000,
            "change_detection_interval_ms": 1000,
            "max_fps": 2,
            "skip_ocr_when_no_change": True,
        }
        assumptions: List[str] = ["未显式指定采样频率时默认按 1 秒 1 次 OCR / 变化检测执行"]
        if "一秒两张" in prompt or "1秒2张" in prompt or "每秒2张" in prompt:
            sampling["screenshot_interval_ms"] = 500
            sampling["max_fps"] = 2
            assumptions = []
        elif "一秒五张" in prompt or "1秒5张" in prompt or "每秒5张" in prompt:
            sampling["screenshot_interval_ms"] = 200
            sampling["max_fps"] = 5
            assumptions = []
        elif "三秒一张" in prompt or "3秒1张" in prompt or "每3秒1张" in prompt:
            sampling["screenshot_interval_ms"] = 3000
            sampling["ocr_interval_ms"] = 3000
            sampling["change_detection_interval_ms"] = 3000
            sampling["max_fps"] = 1
            assumptions = []
        return sampling, assumptions

    def _build_memory(self, prompt: str) -> Tuple[Dict[str, Any], List[str]]:
        memory = {
            "short_term": {"enabled": True, "retain_minutes": 15, "detail_level": "high"},
            "long_term": {
                "enabled": True,
                "retain_hours": 24,
                "max_retain_hours": 72,
                "summary_interval_minutes": 5,
                "detail_level": "summary",
            },
        }
        assumptions = [
            "未显式指定短期记忆时默认保留 15 分钟",
            "未显式指定长期记忆时默认保留 24 小时",
        ]
        short_match = re.search(r"(?:短期记忆|短期保留|详细记忆).*?([0-9]{1,2})\s*分钟", prompt)
        if short_match:
            value = max(1, min(int(short_match.group(1)), 15))
            memory["short_term"]["retain_minutes"] = value
            assumptions = [item for item in assumptions if "短期记忆" not in item]
        long_match = re.search(r"(?:长期记忆|长期保留|长期监控).*?([0-9]{1,2})\s*小时", prompt)
        if long_match:
            value = max(1, min(int(long_match.group(1)), 72))
            memory["long_term"]["retain_hours"] = value
            assumptions = [item for item in assumptions if "长期记忆" not in item]
        return memory, assumptions

    def _build_vision(self, prompt: str) -> Tuple[Dict[str, Any], List[str]]:
        vision = {
            "enabled": False,
            "provider": "ollama",
            "model": "Molmo-7B-D-0924",
            "trigger_when_ocr_sparse": True,
            "ocr_sparse_min_chars": 12,
            "trigger_on_visual_regions": True,
            "trigger_on_watch_intent": True,
            "trigger_on_question_semantics": True,
            "max_calls_per_minute": 6,
        }
        assumptions: List[str] = []
        visual_keywords = ["图表", "图片", "视觉", "看图", "颜色", "图标", "按钮"]
        if any(keyword in prompt for keyword in visual_keywords):
            vision["enabled"] = True
            assumptions.append("请求中包含视觉理解诉求，已建议开启本地视觉增强")
        return vision, assumptions

    def _build_alert(self, *, mode: str, webhook_url: Optional[str]) -> Dict[str, Any]:
        return {
            "enabled": mode == "triggered",
            "channel": "wecom_webhook",
            "webhook_url_env": "AYES_WECOM_WEBHOOK_URL",
            "webhook_url": (webhook_url or "").strip(),
            "priority_threshold": "medium",
            "cooldown_sec": 120,
            "dedupe_window_sec": 300,
        }

    def _build_refresh_click(self, prompt: str) -> Tuple[Dict[str, Any], List[PlanIssue], List[str]]:
        refresh = {
            "enabled": False,
            "coordinate_space": "window",
            "interval_sec": 30,
            "cooldown_sec": 30,
            "max_clicks_per_hour": 120,
            "pause_when_target_matched": True,
        }
        issues: List[PlanIssue] = []
        assumptions: List[str] = []
        if any(keyword in prompt for keyword in ["刷新", "自动点击", "点一下", "点刷新"]):
            refresh["enabled"] = True
            issues.append(PlanIssue(field="actions.refresh_click.point", reason="检测到刷新诉求，但尚未提供点击坐标"))
            assumptions.append("已识别到刷新点击意图，默认刷新间隔 30 秒")
        return refresh, issues, assumptions

    def _normalize_target(self, target: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(target, dict):
            return {}
        target_type = str(target.get("type") or "").strip()
        if target_type == "screen":
            return {"type": "screen", "screen_id": int(target.get("screen_id", 1))}
        if target_type == "window" and target.get("window_id") is not None:
            return {"type": "window", "window_id": int(target["window_id"])}
        if target_type == "process":
            normalized: Dict[str, Any] = {"type": "process"}
            if target.get("process_name"):
                normalized["process_name"] = str(target["process_name"]).strip()
            if target.get("process_id") is not None:
                normalized["process_id"] = int(target["process_id"])
            if len(normalized) > 1:
                return normalized
        return {}

    def _build_target_summary(self, target: Dict[str, Any]) -> str:
        target_type = target.get("type")
        if target_type == "process":
            label = target.get("process_name") or target.get("process_id")
            return f"将监控进程 {label} 的代表业务窗口"
        if target_type == "window":
            return f"将监控窗口 {target.get('window_id')}"
        if target_type == "screen":
            return f"将监控屏幕 {target.get('screen_id')}"
        return "将监控已选择目标"

    def _build_trigger_summary(self, watch_intent: Dict[str, Any]) -> str:
        rules = watch_intent.get("rules") or []
        queries = watch_intent.get("queries") or []
        if rules:
            first = rules[0]
            return (
                f"命中条件为 {first.get('field') or 'numeric_field'} "
                f"{first.get('operator')} {first.get('value')}"
            )
        if queries:
            return f"命中以下监控查询时触发：{', '.join(queries[:3])}"
        return "命中监控条件时触发"

    def _dedupe_strs(self, values: List[str]) -> List[str]:
        unique: List[str] = []
        for value in values:
            cleaned = str(value or "").strip()
            if cleaned and cleaned not in unique:
                unique.append(cleaned)
        return unique
