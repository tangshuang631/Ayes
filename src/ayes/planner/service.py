"""Heuristic planner from natural language to watch-spec drafts."""

from __future__ import annotations

import copy
import re
from uuid import uuid4
from typing import Any, Dict, List, Optional, Tuple

from ayes.config.models import DEFAULT_SAMPLING_INTERVAL_MS, WatchSpec
from ayes.planner.models import ActionIntent, PlanIssue, PlanQuestion, RegionIntent, SetupGuidance, WatchPlanDraft


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
        questions: List[PlanQuestion] = []
        region_intents: List[RegionIntent] = []
        action_intents: List[ActionIntent] = []
        setup_guidance: List[SetupGuidance] = []
        ambiguities: List[PlanIssue] = []
        assumptions: List[str] = []
        confirmation_summary: List[str] = []

        resolved_target = self._normalize_target(target or {})
        if resolved_target:
            draft_spec["target"] = resolved_target
            confirmation_summary.append(self._build_target_summary(resolved_target))
        else:
            missing_fields.append(PlanIssue(field="target", reason="尚未指定监控目标"))
            questions.append(
                PlanQuestion(
                    question_id="q_target_missing",
                    kind="target_missing",
                    field="target",
                    prompt="这次要监控哪个目标，是整个屏幕、某个进程还是某个窗口？",
                    suggested_answer="先监控 Safari 进程",
                )
            )

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
            questions.append(
                PlanQuestion(
                    question_id="q_webhook_missing",
                    kind="webhook_missing",
                    field="alert.webhook_url",
                    prompt="这个 triggered 任务要通知到哪里？请补一个企业微信 webhook URL。",
                    suggested_answer="使用企业微信 webhook 通知我",
                )
            )
            setup_guidance.append(
                SetupGuidance(
                    guidance_id="setup_wecom_webhook",
                    topic="wecom_webhook",
                    status="needs_user_setup",
                    summary="当前任务需要企业微信 webhook 才能真正发出提醒。",
                    blocking_fields=["alert.webhook_url"],
                    user_steps=[
                        "在企业微信群机器人配置页创建或查看现有 webhook。",
                        "把完整 webhook URL 发给 agent，或让 agent 在确认后替你写入任务配置。",
                        "确认提醒对象、冷却时间和去重策略是否符合预期。",
                    ],
                    agent_steps=[
                        "优先继续追问 questions[] 里的 webhook_missing，而不是直接中断任务。",
                        "当用户给出 webhook URL 后，写入 confirm-plan 的 webhook_url 并继续装载任务。",
                        "若用户不知道怎么获取 webhook，重复用结构化步骤指导，直到用户补齐或改成 observe 模式。",
                    ],
                    commands=[
                        "ayes-agent-local plan-spec --task-id <task_id> --prompt \"...\" --target-type process --process-name \"...\"",
                        "ayes-agent-local confirm-plan --plan-file /tmp/<task_id>.plan.json --webhook-url \"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx\"",
                    ],
                    can_agent_attempt_after_permission=False,
                )
            )
        if mode == "triggered":
            confirmation_summary.append(self._build_trigger_summary(watch_intent))
        else:
            confirmation_summary.append("将持续保留近期事件、记忆与可回放证据，不主动发送告警")

        region_intents, region_questions = self._build_region_intents(cleaned_prompt)
        questions.extend(region_questions)

        refresh_click, refresh_issues, refresh_questions, refresh_actions, refresh_assumptions = self._build_refresh_click(cleaned_prompt)
        draft_spec["actions"] = {"refresh_click": refresh_click}
        missing_fields.extend(refresh_issues)
        questions.extend(refresh_questions)
        action_intents.extend(refresh_actions)
        assumptions.extend(refresh_assumptions)
        if refresh_click.get("enabled"):
            confirmation_summary.append("已识别到刷新诉求，但仍需确认刷新点击坐标")
        if region_intents:
            confirmation_summary.append("已识别到重点监控区域诉求，后续需逐条确认区域名称、用途和绑定状态")
            action_intents.insert(
                0,
                ActionIntent(
                    action_type="region_binding",
                    purpose="为重点监控区域补齐绑定和坐标",
                    required_confirmation=True,
                    missing_fields=["target.regions"],
                ),
            )

        short_memory = draft_spec["memory"]["short_term"]
        long_memory = draft_spec["memory"]["long_term"]
        short_label = f"{short_memory['retain_days']} 天" if "retain_days" in short_memory else f"{short_memory['retain_minutes']} 分钟"
        long_label = f"{long_memory['retain_days']} 天" if "retain_days" in long_memory else f"{long_memory['retain_hours']} 小时"
        confirmation_summary.append(f"短期详细记忆保留 {short_label}，长期简略记忆保留 {long_label}")
        if draft_spec["vision"]["enabled"]:
            confirmation_summary.append(f"已建议开启视觉增强模型 {draft_spec['vision']['model']}，这是当前默认本地视觉模型")
            confirmation_summary.append("若本机未安装 Ollama、未启动服务或未拉取默认模型，agent 应先提示用户执行安装/启动/拉取步骤；在获得权限后，agent 也可代为完成并再开启本地视觉增强")
            if int(draft_spec["vision"].get("sampling_every_n_runs") or 1) > 1:
                confirmation_summary.append(f"本地视觉模型将按每隔 {draft_spec['vision']['sampling_every_n_runs']} 次截图触发一次")
            if int(draft_spec["vision"].get("sampling_min_interval_sec") or 0) > 0:
                confirmation_summary.append(f"本地视觉模型最少间隔 {draft_spec['vision']['sampling_min_interval_sec']} 秒")
            setup_guidance.append(
                SetupGuidance(
                    guidance_id="setup_local_vision",
                    topic="local_vision",
                    status="optional_enablement",
                    summary="当前任务适合按需启用本地视觉增强，但仍应保持 OCR-first。",
                    blocking_fields=[],
                    user_steps=[
                        "只有当用户明确希望开启本地大模型增强时，才执行 vision prepare。",
                        "若本机缺 Ollama、缺服务或缺默认模型，按返回步骤安装、启动、拉取 qwen2.5vl:7b。",
                        "启用后继续按高视觉负载规则使用，不要把简单纯文本任务也交给本地视觉模型。",
                    ],
                    agent_steps=[
                        "先通过对话确认用户是否真的要开启本地视觉增强。",
                        "只有在用户明确要求开启时，才调用 vision prepare；不要在 observe-live 阶段主动探测。",
                        "若 prepare 返回 ready，再写入 vision enable；否则重复输出修复建议，直到用户补齐或放弃。",
                    ],
                    commands=[
                        "ayes-agent-local vision prepare --requested-by agent_enable_local_vision",
                        "ayes-agent-local vision enable --provider ollama --model qwen2.5vl:7b --auto-use-when-available true",
                        "ayes-agent-local vision status",
                    ],
                    can_agent_attempt_after_permission=True,
                )
            )
        else:
            confirmation_summary.append("当前任务以文字和数字读取为主，默认不启用本地视觉增强")
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
            questions=questions,
            region_intents=region_intents,
            action_intents=action_intents,
            setup_guidance=setup_guidance,
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
        alert_message_title = str(confirmations.get("alert_message_title") or "").strip()
        if alert_message_title:
            spec_payload.setdefault("alert", {})["message_title"] = alert_message_title
        alert_message_template = str(confirmations.get("alert_message_template") or "").strip()
        if alert_message_template:
            spec_payload.setdefault("alert", {})["message_template"] = alert_message_template

        target_override = confirmations.get("target")
        if isinstance(target_override, dict) and target_override:
            spec_payload["target"] = self._normalize_target(target_override)

        regions = confirmations.get("regions")
        if isinstance(regions, list) and regions:
            spec_payload.setdefault("target", {})["regions"] = regions

        region_bindings = confirmations.get("region_bindings")
        if isinstance(region_bindings, list) and region_bindings:
            spec_payload.setdefault("target", {})["regions"] = [
                {
                    "region_id": item["region_id"],
                    "name": item["name"],
                    "x": int(item["x"]),
                    "y": int(item["y"]),
                    "w": int(item["w"]),
                    "h": int(item["h"]),
                    "coordinate_space": item.get("coordinate_space") or "target",
                    "enabled": True,
                }
                for item in region_bindings
            ]
            payload["region_bindings"] = region_bindings
            existing_intents = payload.get("region_intents") or plan_payload.get("region_intents") or []
            bound_ids = {str(item.get("region_intent_id") or "").strip() for item in region_bindings}
            normalized_intents = []
            unbound_region_intents = []
            for item in existing_intents:
                normalized = dict(item)
                region_intent_id = str(normalized.get("region_intent_id") or "").strip()
                if region_intent_id and region_intent_id in bound_ids:
                    normalized["status"] = "bound"
                else:
                    normalized["status"] = normalized.get("status") or "needs_binding"
                    if normalized.get("required", True):
                        unbound_region_intents.append(normalized)
                normalized_intents.append(normalized)
            payload["region_intents"] = normalized_intents
            payload["unbound_region_intents"] = unbound_region_intents

        region_intents = confirmations.get("region_intents")
        if isinstance(region_intents, list) and region_intents:
            payload["region_intents"] = region_intents

        refresh_click_point = confirmations.get("refresh_click_point")
        refresh_click_enabled = confirmations.get("refresh_click_enabled")
        refresh_click_interval_sec = confirmations.get("refresh_click_interval_sec")
        refresh_click_coordinate_space = confirmations.get("refresh_click_coordinate_space")
        refresh_click = spec_payload.setdefault("actions", {}).setdefault("refresh_click", {})
        if isinstance(refresh_click_enabled, bool):
            refresh_click["enabled"] = refresh_click_enabled
        if refresh_click_interval_sec is not None:
            refresh_click["interval_sec"] = int(refresh_click_interval_sec)
        if refresh_click_coordinate_space:
            refresh_click["coordinate_space"] = str(refresh_click_coordinate_space)
        if isinstance(refresh_click_point, dict) and refresh_click_point:
            refresh_click["enabled"] = True
            refresh_click["point"] = refresh_click_point
            refresh_click.setdefault("coordinate_space", "window")

        if confirmations.get("use_entire_target") is True:
            spec_payload.setdefault("target", {})["regions"] = []

        spec = WatchSpec.from_dict(spec_payload)
        payload["draft_spec"] = spec_payload
        payload["resolved_target"] = self._normalize_target(spec_payload.get("target") or {})
        payload["missing_fields"] = []
        payload["ambiguities"] = []
        payload["can_apply_directly"] = True
        payload["status"] = "ready"
        return spec, payload

    def _build_region_intents(self, prompt: str) -> Tuple[List[RegionIntent], List[PlanQuestion]]:
        intents: List[RegionIntent] = []
        questions: List[PlanQuestion] = []
        wants_regions = any(keyword in prompt for keyword in ["区域", "范围", "只看", "重点区域", "几个区域", "小范围"])
        if "价格" in prompt:
            intents.append(
                RegionIntent(
                    region_intent_id=f"ri_{uuid4().hex[:8]}",
                    name="价格区",
                    purpose="读取当前价格并判断阈值",
                )
            )
        if "库存" in prompt or "有货" in prompt:
            intents.append(
                RegionIntent(
                    region_intent_id=f"ri_{uuid4().hex[:8]}",
                    name="库存区",
                    purpose="读取库存状态和有货变化",
                )
            )
        if "报错" in prompt or "错误" in prompt or "弹窗" in prompt:
            intents.append(
                RegionIntent(
                    region_intent_id=f"ri_{uuid4().hex[:8]}",
                    name="报错区",
                    purpose="识别弹窗和异常提示",
                )
            )
        if intents or wants_regions:
            questions.append(
                PlanQuestion(
                    question_id="q_region_scope",
                    kind="region_scope",
                    field="target.regions",
                    prompt="这次要监控整个目标，还是只监控几个重点区域？",
                    suggested_answer="只监控几个重点区域",
                )
            )
        if intents:
            questions.append(
                PlanQuestion(
                    question_id="q_region_definition",
                    kind="region_definition",
                    field="target.regions",
                    prompt="已识别出重点区域意图，请确认这些区域名称和用途是否正确。",
                    suggested_answer="保留价格区和库存区",
                )
            )
            questions.append(
                PlanQuestion(
                    question_id="q_region_binding",
                    kind="region_binding",
                    field="target.regions",
                    prompt="这些重点区域还没有坐标绑定，请提供外部选择器或截图标注结果。",
                    suggested_answer="后续提供 region_bindings 结果",
                )
            )
        return intents, questions

    def _build_default_spec(self, *, mode: str) -> Dict[str, Any]:
        return {
            "spec_version": "1.0",
            "mode": mode,
            "target": {},
            "sampling": {
                "screenshot_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
                "ocr_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
                "change_detection_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
                "max_fps": 2,
                "skip_ocr_when_no_change": True,
            },
            "vision": {
                "enabled": False,
                "provider": "ollama",
                "model": "qwen2.5vl:7b",
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
                    "retain_days": 7,
                    "detail_level": "high",
                },
                "long_term": {
                    "enabled": True,
                    "retain_days": 14,
                    "max_retain_hours": 720,
                    "summary_interval_minutes": 5,
                    "detail_level": "summary",
                },
                "disable_auto_cleanup": False,
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
                "message_title": "",
                "message_template": "",
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

        explicit_trigger_match = re.search(
            r"(?:出现|看到|显示|变成|包含)\s*([A-Za-z0-9\u4e00-\u9fff_.\-]{2,32})\s*时提醒我",
            prompt,
        )
        if explicit_trigger_match:
            queries.append(explicit_trigger_match.group(1).strip())

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
            "screenshot_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
            "ocr_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
            "change_detection_interval_ms": DEFAULT_SAMPLING_INTERVAL_MS,
            "max_fps": 2,
            "skip_ocr_when_no_change": True,
        }
        assumptions: List[str] = ["未显式指定采样频率时默认按 6 秒 1 次截图 / OCR / 变化检测执行"]
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
            "short_term": {"enabled": True, "retain_days": 7, "detail_level": "high"},
            "long_term": {
                "enabled": True,
                "retain_days": 14,
                "max_retain_hours": 720,
                "summary_interval_minutes": 5,
                "detail_level": "summary",
            },
            "disable_auto_cleanup": False,
        }
        assumptions = [
            "未显式指定短期详细记忆时默认保留 7 天",
            "未显式指定长期简略记忆时默认保留 14 天",
        ]
        short_days_match = re.search(r"(?:短期记忆|短期保留|详细记忆).*?([0-9]{1,2})\s*天", prompt)
        if short_days_match:
            value = max(1, min(int(short_days_match.group(1)), 14))
            memory["short_term"]["retain_days"] = value
            assumptions = [item for item in assumptions if "短期" not in item]
        short_match = re.search(r"(?:短期记忆|短期保留|详细记忆).*?([0-9]{1,2})\s*分钟", prompt)
        if short_match:
            value = max(1, min(int(short_match.group(1)), 15))
            memory["short_term"]["retain_minutes"] = value
            memory["short_term"].pop("retain_days", None)
            assumptions = [item for item in assumptions if "短期记忆" not in item]
        long_days_match = re.search(r"(?:长期记忆|长期保留|长期监控).*?([0-9]{1,2})\s*天", prompt)
        if long_days_match:
            value = max(1, min(int(long_days_match.group(1)), 30))
            memory["long_term"]["retain_days"] = value
            assumptions = [item for item in assumptions if "长期" not in item]
        long_match = re.search(r"(?:长期记忆|长期保留|长期监控).*?([0-9]{1,2})\s*小时", prompt)
        if long_match:
            value = max(1, min(int(long_match.group(1)), 720))
            memory["long_term"]["retain_hours"] = value
            memory["long_term"].pop("retain_days", None)
            assumptions = [item for item in assumptions if "长期记忆" not in item]
        if "永久保留" in prompt or "不自动清理" in prompt:
            memory["disable_auto_cleanup"] = True
        return memory, assumptions

    def _build_vision(self, prompt: str) -> Tuple[Dict[str, Any], List[str]]:
        vision = {
            "enabled": False,
            "provider": "ollama",
            "model": "qwen2.5vl:7b",
            "trigger_when_ocr_sparse": True,
            "ocr_sparse_min_chars": 12,
            "trigger_on_visual_regions": True,
            "trigger_on_watch_intent": True,
            "trigger_on_question_semantics": True,
            "disable_for_text_only_tasks": True,
            "disable_for_numeric_only_tasks": True,
            "disable_for_threshold_rules": True,
            "sampling_every_n_runs": 1,
            "sampling_min_interval_sec": 0,
            "max_calls_per_minute": 6,
        }
        assumptions: List[str] = []
        visual_keywords = ["图表", "图片", "视觉", "看图", "颜色", "图标", "按钮", "布局", "曲线", "走势", "仪表盘"]
        simple_text_only_keywords = ["只看文字", "只看文本", "只看数字", "不需要看图", "不需要颜色", "不需要按钮", "不需要图表"]
        if any(keyword in prompt for keyword in simple_text_only_keywords):
            assumptions.append("当前任务以文字和数字读取为主，默认不启用本地视觉增强")
            return vision, assumptions
        if any(keyword in prompt for keyword in visual_keywords):
            vision["enabled"] = True
            assumptions.append("请求中包含高视觉理解诉求，已建议在需要时开启本地视觉增强")
        every_n_runs_match = re.search(r"每隔\s*([0-9]{1,3})\s*次(?:截图|采样|图片)", prompt)
        if every_n_runs_match:
            vision["sampling_every_n_runs"] = max(1, int(every_n_runs_match.group(1)))
            vision["enabled"] = True
            assumptions.append(f"已按对话要求设置为每隔 {vision['sampling_every_n_runs']} 次截图再调用一次本地视觉模型")
        min_interval_match = re.search(r"(?:至少间隔|最少间隔|间隔)\s*([0-9]{1,4})\s*秒", prompt)
        if min_interval_match:
            vision["sampling_min_interval_sec"] = max(0, int(min_interval_match.group(1)))
            vision["enabled"] = True
            assumptions.append(f"已按对话要求设置本地视觉模型最少间隔 {vision['sampling_min_interval_sec']} 秒")
        return vision, assumptions

    def _build_alert(self, *, mode: str, webhook_url: Optional[str]) -> Dict[str, Any]:
        return {
            "enabled": mode == "triggered",
            "channel": "wecom_webhook",
            "webhook_url_env": "AYES_WECOM_WEBHOOK_URL",
            "webhook_url": (webhook_url or "").strip(),
            "message_title": "",
            "message_template": "",
            "priority_threshold": "medium",
            "cooldown_sec": 120,
            "dedupe_window_sec": 300,
        }

    def _build_refresh_click(self, prompt: str) -> Tuple[Dict[str, Any], List[PlanIssue], List[PlanQuestion], List[ActionIntent], List[str]]:
        refresh = {
            "enabled": False,
            "coordinate_space": "window",
            "interval_sec": 30,
            "cooldown_sec": 30,
            "max_clicks_per_hour": 120,
            "pause_when_target_matched": True,
        }
        issues: List[PlanIssue] = []
        questions: List[PlanQuestion] = []
        action_intents: List[ActionIntent] = []
        assumptions: List[str] = []
        if any(keyword in prompt for keyword in ["刷新", "自动点击", "点一下", "点刷新"]):
            refresh["enabled"] = True
            issues.append(PlanIssue(field="actions.refresh_click.point", reason="检测到刷新诉求，但尚未提供点击坐标"))
            questions.append(
                PlanQuestion(
                    question_id="q_refresh_click_enable",
                    kind="refresh_click_enable",
                    field="actions.refresh_click.enabled",
                    prompt="要不要真的启用自动刷新点击？",
                    suggested_answer="启用自动刷新点击",
                )
            )
            questions.append(
                PlanQuestion(
                    question_id="q_refresh_click_point",
                    kind="refresh_click_point",
                    field="actions.refresh_click.point",
                    prompt="刷新点击点还没绑定，需要补充点击坐标或后续绑定方式。",
                    suggested_answer="后续绑定刷新按钮点击点",
                )
            )
            action_intents.append(
                ActionIntent(
                    action_type="refresh_click",
                    purpose="周期性刷新页面以便发现状态变化",
                    required_confirmation=True,
                    missing_fields=["actions.refresh_click.point"],
                )
            )
            assumptions.append("已识别到刷新点击意图，默认刷新间隔 30 秒")
            interval_match = re.search(r"每\s*([0-9]+)\s*秒", prompt)
            if interval_match:
                refresh["interval_sec"] = int(interval_match.group(1))
                assumptions = [item for item in assumptions if "默认刷新间隔 30 秒" not in item]
            else:
                questions.append(
                    PlanQuestion(
                        question_id="q_refresh_click_interval",
                        kind="refresh_click_interval",
                        field="actions.refresh_click.interval_sec",
                        prompt="自动刷新点击间隔多少秒合适？",
                        suggested_answer="每 30 秒点一次",
                    )
                )
        return refresh, issues, questions, action_intents, assumptions

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
