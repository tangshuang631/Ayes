"""Compact memory facts shared by memory files and search indexes."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

from ayes.events.models import TimelineEvent


CONTROLLED_FACT_SCENES = {
    "页面": "pg",
    "弹窗": "dlg",
    "图表": "cht",
    "表格": "tbl",
    "列表": "lst",
    "内容": "cnt",
    "画面": "vis",
    "卡片": "crd",
    "状态": "sts",
    "表单": "frm",
    "导航": "nav",
    "控件": "ctl",
    "PPT": "ppt",
    "聊天": "chat",
    "主体": "subj",
}


@dataclass(frozen=True)
class MemoryFact:
    task_id: str
    timestamp: float
    info: str
    code: str = ""
    region: str = ""
    scene: str = ""
    region_slot: str = ""
    pos: str = ""
    sub: str = ""
    subj: str = ""
    ctx: str = ""
    bg: str = ""
    source: str = ""
    event_type: str = ""
    confidence: float = 0.0
    event_id: str = ""
    target: str = ""
    tags: tuple[str, ...] = ()

    def to_short_payload(self, *, time_text: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "time": time_text if time_text is not None else str(self.timestamp),
            "info": self.info,
        }
        if self.code:
            payload["code"] = self.code
        if self.region:
            payload["region"] = self.region
        return payload

    def to_index_chunk(self) -> dict[str, Any]:
        return {
            "chunk_id": self.event_id or f"fact:{self.task_id}:{int(self.timestamp)}:{self.info[:16]}",
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "layer": "short",
            "source": self.source,
            "event_type": self.event_type,
            "info": self.info,
            "code": self.code,
            "scene": self.scene,
            "region_slot": self.region_slot,
            "k1": self.subj,
            "k2": self.ctx,
            "k3": self.bg,
            "pos": self.pos,
            "sub": self.sub,
            "subj": self.subj,
            "ctx": self.ctx,
            "bg": self.bg,
            "region": self.region,
            "target": self.target,
            "tags": list(self.tags),
            "confidence": self.confidence,
        }


class MemoryFactExtractor:
    """Extract one compact, answerable fact from a timeline event."""

    def __init__(self) -> None:
        self._rules = _FactRuleEngine()

    def extract(self, event: TimelineEvent) -> Optional[MemoryFact]:
        payload = self._rules.compact_event(event)
        if payload is None:
            return None
        code = str(payload.get("code") or "")
        fields = _parse_fact_code(code)
        region = str(payload.get("region") or "")
        return MemoryFact(
            task_id=event.task_id,
            timestamp=float(event.timestamp),
            info=str(payload.get("info") or ""),
            code=code,
            region=region,
            scene=fields.get("scene") or "",
            region_slot=fields.get("reg") or "",
            pos=fields.get("pos") or "",
            sub=fields.get("sub") or "",
            subj=fields.get("subj") or "",
            ctx=fields.get("ctx") or "",
            bg=fields.get("bg") or "",
            source=event.source,
            event_type=event.event_type,
            confidence=float(event.confidence or 0.0),
            event_id=event.event_id,
            target=_target_label(event),
            tags=tuple(str(tag) for tag in event.tags[:8]),
        )


class _FactRuleEngine:
    """Classify noisy OCR/VLM events into compact, indexed memory facts."""

    def compact_event(self, event: TimelineEvent) -> Optional[dict[str, Any]]:
        if event.event_type in {"vision_skipped", "vision_triggered"}:
            return None
        if self._is_low_value_memory_event(event) or self._is_low_confidence_ocr(event):
            return None
        info = self._best_event_info(event)
        if not info or self._looks_like_gibberish(info):
            return None
        info = self._prefer_fact_like_info(event, info)
        info = self._compact_list_like_info(event, info)
        if self._is_low_information_fragment(event, info) or self._is_medium_quality_noise(event, info):
            return None
        region_name = str(event.region.name or event.region.region_id or "")
        code = self._build_compact_info_code(info, region=region_name) if self._should_emit_compact_code(info) else ""
        short_info = self._short_info_from_code(info, code=code)
        if not short_info:
            return None
        payload: dict[str, Any] = {"info": short_info}
        if code:
            payload["code"] = code
        region = self._compact_region_name(event)
        if region:
            payload["region"] = region
        return payload

    def _is_low_value_memory_event(self, event: TimelineEvent) -> bool:
        summary = str(event.summary or "").strip()
        if event.source == "diff" and summary.startswith("未检测到显著变化"):
            return True
        if event.event_type == "visual_change" and summary.startswith("未检测到显著变化"):
            return True
        if "已忽略原文" in summary and "低置信 OCR" in summary:
            return True
        capture_status = str(getattr(getattr(event, "observability", None), "capture_status", "") or "").strip()
        if event.source == "capture" and event.event_type == "capture_status":
            return capture_status in {"process_window_not_found", "window_not_found", "not_running"} or "未找到可采集业务窗口" in summary
        return False

    def _is_low_confidence_ocr(self, event: TimelineEvent) -> bool:
        if event.source != "ocr":
            return False
        attributes = event.visual.attributes or {}
        score = float(attributes.get("text_quality_score") or 1.0)
        return bool(attributes.get("text_quality_noisy")) or score < 0.35 or str(event.summary or "").startswith("OCR 低质量文本已降权")

    def _compact_region_name(self, event: TimelineEvent) -> str:
        region = str(event.region.name or event.region.region_id or "").strip()
        if not region or region in {"全目标", "自动全目标"}:
            return ""
        return self._trim_info(region)

    def _best_event_info(self, event: TimelineEvent) -> str:
        for value in [event.summary, event.text.ocr_text or event.text.normalized_text, event.visual.summary]:
            text = self._trim_info(str(value or "").strip())
            if not text:
                continue
            if text.startswith(("OCR vision |", "视觉增强已跳过", "视觉增强已触发")):
                continue
            return text
        return ""

    def _prefer_fact_like_info(self, event: TimelineEvent, info: str) -> str:
        window_title = self._trim_info(str(event.target.window_title or "").strip())
        if event.event_type in {"target_window_changed", "window_title_changed"} and len(window_title) >= 4:
            return f"页面：{window_title}"
        observation = self._structured_observation(event)
        detail_lines = self._observation_detail_lines(observation)
        labels = {str(item).strip().lower() for item in list((observation.get("labels") or [])) if str(item).strip()}
        summaries = [
            self._trim_info(str(event.visual.summary or "").strip()),
            self._trim_info(str(event.summary or "").strip()),
            self._trim_info(str(((observation.get("visual") or {}).get("summary") or "")).strip()),
        ]
        is_visual = event.event_type == "visual_summary" or event.source == "vision" or bool(detail_lines) or bool(labels)
        if is_visual and not detail_lines and (self._looks_like_visual_noise_summary(info) or self._looks_like_visual_noise_summary(str(event.visual.summary or ""))):
            return ""
        if not is_visual:
            region_name = self._compact_region_name(event)
            if len(window_title) >= 4 and self._looks_like_login(summaries, detail_lines):
                return f"页面：{window_title}"
            if region_name in {"自动主内容区", "主内容区"} and len(window_title) >= 4 and self._looks_like_page(summaries):
                return f"页面：{window_title}"
            return info

        scene_checks = [
            ("PPT", "ppt", self._looks_like_ppt),
            ("弹窗", "dlg", self._looks_like_dialog),
            ("表单", "frm", self._looks_like_form),
            ("聊天", "chat", self._looks_like_chat),
            ("导航", "nav", self._looks_like_navigation),
            ("控件", "ctl", self._looks_like_control),
            ("主体", "subj", self._looks_like_subject),
            ("图表", "cht", self._looks_like_chart),
            ("表格", "tbl", self._looks_like_table),
            ("卡片", "crd", self._looks_like_card),
            ("内容", "cnt", self._looks_like_content),
            ("画面", "vis", self._looks_like_scene),
            ("状态", "sts", self._looks_like_status),
        ]
        for label, _alias, predicate in scene_checks:
            if not predicate(summaries, detail_lines, labels):
                continue
            fallback = self._extract_dialog_details(summaries) if label == "弹窗" else self._extract_visual_details(summaries)
            details = self._join_fact_details(detail_lines, fallback=fallback)
            if not details:
                continue
            if label == "画面" and self._is_too_generic_scene_fact(details):
                return ""
            return f"{label}：{details}"
        if len(window_title) >= 4 and self._looks_like_login(summaries, detail_lines):
            return f"页面：{window_title}"
        return info

    def _compact_list_like_info(self, event: TimelineEvent, info: str) -> str:
        items = self._extract_time_labeled_items(info)
        if len(items) < 3:
            return info
        target_name = " ".join([event.task_id or "", event.target.process_name or "", event.target.window_title or ""]).lower()
        return self._trim_info(self._list_prefix_for_event(event, target_name=target_name, items=items) + "；".join(items[:6]))

    def _list_prefix_for_event(self, event: TimelineEvent, target_name: str, items: list[str]) -> str:
        if "微信" in target_name or "wechat" in target_name:
            return "微信会话列表："
        region_name = self._compact_region_name(event)
        if region_name in {"自动左侧栏", "左侧栏"} and self._looks_like_sidebar_list_context(event, target_name=target_name, items=items):
            return "左侧列表："
        if region_name in {"自动右侧栏", "右侧栏"} and self._looks_like_sidebar_list_context(event, target_name=target_name, items=items):
            return "右侧列表："
        if region_name in {"自动顶部栏", "顶部栏"} and self._looks_like_sidebar_list_context(event, target_name=target_name, items=items):
            return "顶部列表："
        if region_name in {"自动底部栏", "底部栏"} and self._looks_like_sidebar_list_context(event, target_name=target_name, items=items):
            return "底部列表："
        return "时间列表："

    def _structured_observation(self, event: TimelineEvent) -> dict[str, Any]:
        observation = (event.visual.attributes or {}).get("structured_observation") or {}
        return observation if isinstance(observation, dict) else {}

    def _observation_detail_lines(self, observation: dict[str, Any]) -> list[str]:
        values = observation.get("detail_lines") or ((observation.get("visual") or {}).get("detail_lines") or [])
        lines: list[str] = []
        for item in list(values or []):
            text = self._trim_info(str(item or "").strip(" ，。,.；;"))
            if not text or self._is_low_value_detail_line(text):
                continue
            if text not in lines:
                lines.append(text)
        return lines[:3]

    def _join_fact_details(self, detail_lines: list[str], *, fallback: list[str]) -> str:
        values = list(detail_lines or []) or [item for item in list(fallback or []) if not self._is_low_value_detail_line(item)]
        cleaned: list[str] = []
        for item in values:
            text = self._compact_slot_value(str(item or "").strip(" ，。,.；;"))
            if not text or self._is_low_value_detail_line(text):
                continue
            if text not in cleaned:
                cleaned.append(text)
        return self._trim_info("，".join(cleaned[:3]))

    def _extract_dialog_details(self, summaries: list[str]) -> list[str]:
        values: list[str] = []
        for summary in summaries:
            for piece in re.split(r"[，,；;]", summary or ""):
                text = self._trim_info(piece.strip(" ，。,.；;"))
                if text and any(token in text for token in ["弹窗", "输入框", "按钮", "确认", "取消"]):
                    text = text.replace("包含", "").replace("出现", "").strip()
                    if text not in values:
                        values.append(text)
        return values[:3]

    def _extract_visual_details(self, summaries: list[str]) -> list[str]:
        values: list[str] = []
        for summary in summaries:
            normalized = str(summary or "")
            for old in ["主内容是一张", "主内容是", "中部是一张", "中部是"]:
                normalized = normalized.replace(old, "")
            for piece in re.split(r"[，,；;]", normalized):
                text = self._compact_slot_value(piece)
                if text and text not in values:
                    values.append(text)
        return values[:3]

    def _build_compact_info_code(self, info: str, *, region: str = "") -> str:
        text = self._trim_info(info)
        if "：" not in text:
            return ""
        prefix, rest = text.split("：", 1)
        scene_alias = CONTROLLED_FACT_SCENES.get(prefix)
        if not scene_alias:
            return ""
        parts = [part.strip() for part in re.split(r"[，,；;]", rest) if part.strip()]
        slots = [f"scene={scene_alias}", f"reg={self._region_slot(region)}"]
        pos = self._position_slot(region=region, parts=parts[:3])
        if pos:
            slots.append(f"pos={pos}")
        sub = self._subregion_slot(parts=parts[:3])
        if sub:
            slots.append(f"sub={sub}")
        for slot_name, part in zip(["subj", "ctx", "bg"], parts[:3]):
            value = self._compact_slot_value(part)
            if value:
                slots.append(f"{slot_name}={value}")
        return "|".join(slots)

    def _region_slot(self, region: str) -> str:
        if "顶部" in region:
            return "top"
        if "左侧" in region:
            return "left"
        if "右侧" in region:
            return "right"
        if "底部" in region:
            return "bottom"
        if "主内容" in region:
            return "main"
        if "全目标" in region:
            return "full"
        return "roi"

    def _position_slot(self, *, region: str, parts: list[str]) -> str:
        haystack = " ".join([region, *parts])
        if "顶部" in region or "上方" in haystack or "顶栏" in haystack:
            return "top"
        if "底部" in region or "下方" in haystack or "底栏" in haystack:
            return "bottom"
        if "左侧" in region:
            return "left"
        if "右侧" in region:
            return "right"
        if "中央" in haystack or "中部" in haystack or "主内容" in region:
            return "center"
        return ""

    def _subregion_slot(self, *, parts: list[str]) -> str:
        haystack = " ".join(parts)
        if "主内容左" in haystack or "左半" in haystack:
            return "main_left"
        if "主内容右" in haystack or "右半" in haystack:
            return "main_right"
        return ""

    def _short_info_from_code(self, info: str, *, code: str) -> str:
        if not code or "：" not in info:
            return info
        prefix, rest = info.split("：", 1)
        first = next((self._compact_slot_value(part) for part in re.split(r"[，,；;]", rest) if part.strip()), "")
        return self._trim_info(f"{prefix}：{first}") if first else info

    def _compact_slot_value(self, value: str) -> str:
        text = self._trim_info(str(value or "").strip(" ，。,.；;"))
        for old in ["标题为", "标题：", "标题:", "显示", "包含"]:
            if text.startswith(old):
                text = text.replace(old, "", 1).strip()
        return self._trim_info(text)

    def _should_emit_compact_code(self, info: str) -> bool:
        text = str(info or "").strip()
        if not text or "：" not in text or text.startswith(("微信会话列表：", "时间列表：", "左侧列表：", "右侧列表：", "顶部列表：", "底部列表：")):
            return False
        prefix = text.split("：", 1)[0]
        return prefix in CONTROLLED_FACT_SCENES

    def _extract_time_labeled_items(self, text: str) -> list[str]:
        normalized = " ".join(str(text or "").split())
        items: list[str] = []
        for match in re.finditer(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", normalized):
            prefix = normalized[max(0, match.start() - 32) : match.start()]
            name = self._clean_list_item_name(prefix)
            if name:
                item = f"{name} {match.group(0)}"
                if item not in items:
                    items.append(item)
        return items

    def _clean_list_item_name(self, value: str) -> str:
        text = re.sub(r"\[[^\]]*\]", " ", str(value or ""))
        text = re.sub(r"[@＠]\S+", " ", text)
        text = re.sub(r"\b\d+\s*$", " ", text)
        parts = [part for part in re.split(r"\s+", text.strip()) if part and ":" not in part and "：" not in part]
        if not parts:
            return ""
        name = parts[-1].strip(" ，。,.|丨·-_:：")
        return self._trim_info(name) if len(name) >= 2 else ""

    def _looks_like_sidebar_list_context(self, event: TimelineEvent, *, target_name: str, items: list[str]) -> bool:
        hints = " ".join([target_name, str(event.summary or ""), str(event.visual.summary or ""), " ".join(items[:4])]).lower()
        return any(token in hints for token in ["chat", "slack", "discord", "wechat", "会话", "群", "联系人", "频道", "未读", "私聊", "群聊"])

    def _looks_like_dialog(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["弹窗", "对话框", "dialog", "modal"])

    def _looks_like_chart(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["图表", "折线图", "柱状图", "饼图", "趋势图", "chart", "chart_like"])

    def _looks_like_table(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["表格", "数据表", "table", "价格列", "库存列", "字段列", "多行数据", "数据行"])

    def _looks_like_card(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["卡片", "card", "缩略图", "推荐卡", "商品卡", "视频卡"])

    def _looks_like_form(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["表单", "登录表单", "验证码", "手机号", "密码", "搜索框"])

    def _looks_like_navigation(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["导航", "页签", "标签导航", "tab", "选中设置页签", "顶部标签"])

    def _looks_like_control(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["按钮", "开关", "下拉", "勾选", "保存按钮", "取消按钮"])

    def _looks_like_ppt(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["ppt", "幻灯片", "缩略图列表", "演示文稿"])

    def _looks_like_chat(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = self._haystack(summaries, detail_lines, labels)
        if any(token in haystack for token in ["登录表单", "验证码", "手机号", "密码"]):
            return False
        return any(token in haystack for token in ["聊天", "联系人", "消息气泡", "输入框", "聊天页面"])

    def _looks_like_subject(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["主体", "图像主体", "主物体", "近景主体"])

    def _looks_like_content(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["文档", "正文", "文章", "ppt", "幻灯片", "要点", "段落", "内容页"])

    def _looks_like_scene(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["视频帧", "主画面", "人物", "字幕", "封面", "插图", "图片", "画面"])

    def _looks_like_status(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        return self._contains_any(summaries, detail_lines, labels, ["错误", "异常", "告警", "警告", "失败", "成功", "重新登录", "提示", "loading", "加载"])

    def _looks_like_login(self, summaries: list[str], detail_lines: list[str]) -> bool:
        return any(token in " ".join([*summaries, *detail_lines]) for token in ["登录", "手机号", "验证码", "账号", "密码"])

    def _looks_like_page(self, summaries: list[str]) -> bool:
        return any(token in " ".join(summaries) for token in ["页面", "网页", "登录", "设置", "表单", "详情"])

    def _contains_any(self, summaries: list[str], detail_lines: list[str], labels: set[str], tokens: list[str]) -> bool:
        haystack = self._haystack(summaries, detail_lines, labels)
        return any(token in haystack for token in tokens)

    def _haystack(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> str:
        return " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()

    def _looks_like_visual_noise_summary(self, value: str) -> bool:
        text = str(value or "").strip()
        return not text or self._looks_like_gibberish(text) or any(token in text for token in ["无意义字符", "字幕碎片", "乱码", "低质量文本"])

    def _is_too_generic_scene_fact(self, value: str) -> bool:
        return str(value or "").strip() in {"", "视频主画面", "主画面是视频帧", "视频帧", "主画面"}

    def _is_low_information_fragment(self, event: TimelineEvent, info: str) -> bool:
        text = str(info or "").strip()
        if not text or re.fullmatch(r"\d{1,2}:\d{2}", text):
            return True
        if self._looks_like_short_fact_label(text):
            return False
        if event.source == "ocr" and "：" not in text and ":" not in text:
            compact = "".join(text.split())
            if len(compact) <= 6:
                return True
            if len([token for token in re.split(r"\s+", text) if token]) <= 2 and len(text) < 14:
                return True
        return False

    def _is_medium_quality_noise(self, event: TimelineEvent, info: str) -> bool:
        if event.source != "ocr":
            return False
        score = float((event.visual.attributes or {}).get("text_quality_score") or 0.0)
        if score < 0.42 or score > 0.72:
            return False
        text = str(info or "").strip()
        if not text or "：" in text:
            return False
        chars = [char for char in text if not char.isspace()]
        if len(chars) < 10:
            return True
        cjk_count = sum(1 for char in chars if "\u4e00" <= char <= "\u9fff")
        ascii_alpha_count = sum(1 for char in chars if char.isascii() and char.isalpha())
        digit_count = sum(1 for char in chars if char.isdigit())
        symbol_count = sum(1 for char in chars if not char.isalnum() and not ("\u4e00" <= char <= "\u9fff"))
        if cjk_count == 0 and ascii_alpha_count >= 10 and (digit_count >= 1 or symbol_count >= 2):
            return True
        return cjk_count == 0 and symbol_count / max(len(chars), 1) > 0.18

    def _is_low_value_detail_line(self, value: str) -> bool:
        text = str(value or "").strip()
        if not text or re.fullmatch(r"\d{1,2}:\d{2}", text):
            return True
        if self._looks_like_short_fact_label(text):
            return False
        if self._looks_like_gibberish(text):
            return True
        compact = "".join(text.split())
        if len(compact) <= 2:
            return True
        cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        ascii_alpha_count = sum(1 for char in text if char.isascii() and char.isalpha())
        digit_count = sum(1 for char in text if char.isdigit())
        symbol_count = sum(1 for char in text if not char.isalnum() and not ("\u4e00" <= char <= "\u9fff") and not char.isspace())
        if cjk_count == 0 and ascii_alpha_count <= 2 and digit_count >= 2:
            return True
        if cjk_count == 0 and ascii_alpha_count >= 3 and digit_count >= 2 and len(compact) <= 18:
            return True
        if cjk_count == 0 and ascii_alpha_count >= 6 and symbol_count >= 2 and len(compact) <= 24:
            return True
        return cjk_count == 0 and symbol_count >= 2 and ascii_alpha_count < 8

    def _looks_like_gibberish(self, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return True
        chars = [char for char in text if not char.isspace()]
        if len(chars) < 3:
            return True
        cjk_count = sum(1 for char in chars if "\u4e00" <= char <= "\u9fff")
        symbol_count = sum(1 for char in chars if not char.isalnum() and not ("\u4e00" <= char <= "\u9fff"))
        digit_count = sum(1 for char in chars if char.isdigit())
        ascii_alpha_count = sum(1 for char in chars if char.isascii() and char.isalpha())
        if cjk_count == 0 and symbol_count >= 3 and (digit_count + symbol_count) / max(len(chars), 1) > 0.45:
            return True
        if cjk_count == 0 and symbol_count / max(len(chars), 1) > 0.35:
            return True
        if cjk_count == 0 and ascii_alpha_count <= 12 and symbol_count >= 2 and digit_count >= 2:
            return True
        return bool(re.search(r"[A-Za-z]\*%[A-Za-z]\*", text))

    def _looks_like_short_fact_label(self, text: str) -> bool:
        return any(token in str(text or "") for token in ["登录", "设置", "页面", "详情", "弹窗", "表单", "导航", "聊天", "PPT", "列表", "会话", "内容区", "主内容区"])

    def _trim_info(self, value: str) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= 180 else text[:177] + "..."


def _parse_fact_code(code: str) -> dict[str, str]:
    fields = {
        "scene": "",
        "reg": "",
        "pos": "",
        "sub": "",
        "subj": "",
        "ctx": "",
        "bg": "",
    }
    for part in str(code or "").split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key in fields:
            fields[key] = str(value or "").strip()
    return fields


def _target_label(event: TimelineEvent) -> str:
    target = event.target
    if target.window_title:
        return target.window_title
    if target.process_name:
        return target.process_name
    if target.screen_id is not None:
        return f"screen:{target.screen_id}"
    return target.type
