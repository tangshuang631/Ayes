"""Task-scoped JSONL memory files for user-auditable retention."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, Optional

from ayes.events.models import TimelineEvent
from ayes.app.task_paths import date_from_timestamp, safe_task_segment, task_runtime_paths


class TaskMemoryFileStore:
    REGION_DUPLICATE_SUPPRESS_SECONDS = 600.0

    def __init__(self, *, runtime_dir: Path, task_path_resolver=None) -> None:
        self.runtime_dir = Path(runtime_dir).resolve()
        self.task_path_resolver = task_path_resolver
        self._last_short_by_path: dict[str, tuple[str, float]] = {}

    def task_dir(self, task_id: str, *, timestamp: float | None = None) -> Path:
        if self.task_path_resolver is not None:
            paths = self.task_path_resolver(task_id, timestamp=timestamp)
            return Path(paths["memory_dir"])
        return task_runtime_paths(self.runtime_dir, task_id, timestamp=timestamp)["memory_dir"]

    def short_event_path(self, *, task_id: str, timestamp: float) -> Path:
        safe_task_id = safe_task_segment(task_id)
        date_text = date_from_timestamp(timestamp)
        return self.task_dir(safe_task_id, timestamp=timestamp) / "short" / f"{date_text}-{safe_task_id}-details.jsonl"

    def long_summary_path(self, *, task_id: str, timestamp: float) -> Path:
        safe_task_id = safe_task_segment(task_id)
        date_text = date_from_timestamp(timestamp)
        return self.task_dir(safe_task_id, timestamp=timestamp) / "long" / f"{date_text}-{safe_task_id}-summary.jsonl"

    def compact_segments_path(self, *, task_id: str, timestamp: float) -> Path:
        safe_task_id = safe_task_segment(task_id)
        date_text = date_from_timestamp(timestamp)
        return self.task_dir(safe_task_id, timestamp=timestamp) / "compact" / f"{date_text}-{safe_task_id}-segments.jsonl"

    def append_short_event(self, event: TimelineEvent) -> Path:
        path = self.short_event_path(task_id=event.task_id, timestamp=event.timestamp)
        payload = self._compact_short_event(event)
        if payload is not None:
            if self._is_duplicate_short_payload(path=path, payload=payload, timestamp=event.timestamp):
                return path
            self._append_jsonl(path, payload)
        return path

    def append_long_summary(self, payload: Dict[str, Any]) -> Path:
        task_id = str(payload.get("task_id") or "unknown")
        timestamp = float(payload.get("window_end") or payload.get("window_start") or 0.0)
        path = self.long_summary_path(task_id=task_id, timestamp=timestamp)
        compact = self._compact_long_summary(payload)
        if compact is not None:
            self._append_jsonl(path, compact)
        return path

    def _append_jsonl(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            output.write("\n")

    def _is_duplicate_short_payload(self, *, path: Path, payload: Dict[str, Any], timestamp: float) -> bool:
        info = str(payload.get("info") or "")
        region = str(payload.get("region") or "")
        if region:
            info = f"{region}\n{info}"
        key = str(path)
        previous = self._last_short_by_path.get(key)
        if previous is None:
            self._last_short_by_path[key] = (info, float(timestamp))
            return False
        previous_info, previous_timestamp = previous
        suppress_seconds = self.REGION_DUPLICATE_SUPPRESS_SECONDS if region else 30.0
        is_duplicate = previous_info == info and (float(timestamp) - previous_timestamp) < suppress_seconds
        if not is_duplicate:
            self._last_short_by_path[key] = (info, float(timestamp))
        return is_duplicate

    def delete_expired_files(self, *, task_id: str, short_cutoff: float, long_cutoff: float) -> Dict[str, int]:
        safe_task_id = safe_task_segment(task_id)
        root = self.runtime_dir / "tasks"
        deleted_short = self._delete_expired_paths(
            root=root,
            safe_task_id=safe_task_id,
            memory_kind="short",
            suffix="-details.jsonl",
            cutoff_timestamp=short_cutoff,
        )
        deleted_long = self._delete_expired_paths(
            root=root,
            safe_task_id=safe_task_id,
            memory_kind="long",
            suffix="-summary.jsonl",
            cutoff_timestamp=long_cutoff,
        )
        return {"deleted_short_files": deleted_short, "deleted_long_files": deleted_long}

    def _delete_expired_paths(self, *, root: Path, safe_task_id: str, memory_kind: str, suffix: str, cutoff_timestamp: float) -> int:
        deleted = 0
        for path in root.glob(f"**/{safe_task_id}/memory/{memory_kind}/*{suffix}"):
            if not path.is_file():
                continue
            date_text = path.name.split("-", 3)
            try:
                file_date = "-".join(date_text[:3])
                file_timestamp = datetime.fromisoformat(file_date).replace(tzinfo=timezone.utc).timestamp()
            except Exception:
                file_timestamp = path.stat().st_mtime
            if file_timestamp >= cutoff_timestamp:
                continue
            try:
                path.unlink()
                deleted += 1
            except OSError:
                pass
        return deleted

    def _compact_short_event(self, event: TimelineEvent) -> Optional[Dict[str, Any]]:
        if event.event_type in {"vision_skipped", "vision_triggered"}:
            return None
        if self._is_low_value_memory_event(event):
            return None
        if self._is_low_confidence_ocr(event):
            return None
        info = self._best_event_info(event)
        if not info or self._looks_like_gibberish(info):
            return None
        info = self._prefer_fact_like_info(event, info)
        info = self._compact_list_like_info(event, info)
        if self._is_low_information_fragment(event, info):
            return None
        if self._is_medium_quality_noise(event, info):
            return None
        payload = {
            "time": self._format_timestamp(event.timestamp),
            "info": info,
        }
        code = self._build_compact_info_code(info, region=event.region.name or event.region.region_id or "") if self._should_emit_compact_code(info) else ""
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
            if capture_status in {"process_window_not_found", "window_not_found", "not_running"}:
                return True
            if "未找到可采集业务窗口" in summary:
                return True
        return False

    def _is_low_confidence_ocr(self, event: TimelineEvent) -> bool:
        if event.source != "ocr":
            return False
        attributes = event.visual.attributes or {}
        summary = str(event.summary or "")
        is_low_quality = bool(attributes.get("text_quality_noisy")) or float(attributes.get("text_quality_score") or 1.0) < 0.35
        return is_low_quality or summary.startswith("OCR 低质量文本已降权")

    def _compact_region_name(self, event: TimelineEvent) -> str:
        region = str(event.region.name or event.region.region_id or "").strip()
        if not region:
            return ""
        if region in {"全目标", "自动全目标"}:
            return ""
        return self._trim_info(region)

    def _compact_list_like_info(self, event: TimelineEvent, info: str) -> str:
        target_name = str(" ".join([event.task_id or "", event.target.process_name or "", event.target.window_title or ""])).lower()
        items = self._extract_time_labeled_items(info)
        if len(items) < 3:
            return info
        prefix = self._list_prefix_for_event(event, target_name=target_name, items=items)
        return self._trim_info(prefix + "；".join(items[:6]))

    def _prefer_fact_like_info(self, event: TimelineEvent, info: str) -> str:
        window_title = self._trim_info(str(event.target.window_title or "").strip())
        if event.event_type in {"target_window_changed", "window_title_changed"} and len(window_title) >= 4:
            return f"页面：{window_title}"
        observation = self._structured_observation(event)
        detail_lines = self._observation_detail_lines(observation)
        if (event.event_type == "visual_summary" or event.source == "vision") and not detail_lines:
            if self._looks_like_visual_noise_summary(info) or self._looks_like_visual_noise_summary(str(event.visual.summary or "")):
                return ""
        labels = {str(item).strip().lower() for item in list((observation.get("labels") or [])) if str(item).strip()}
        summary_candidates = [
            self._trim_info(str(event.visual.summary or "").strip()),
            self._trim_info(str(event.summary or "").strip()),
            self._trim_info(str(((observation.get("visual") or {}).get("summary") or "")).strip()),
        ]
        region_name = self._compact_region_name(event)
        visual_fact_candidate = event.event_type == "visual_summary" or event.source == "vision" or bool(detail_lines) or bool(labels)
        if not visual_fact_candidate:
            if len(window_title) >= 4 and self._looks_like_login(summary_candidates, detail_lines):
                return f"页面：{window_title}"
            if region_name in {"自动主内容区", "主内容区"} and len(window_title) >= 4 and self._looks_like_page(summary_candidates):
                return f"页面：{window_title}"
            return info
        if self._looks_like_ppt(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"PPT：{details}"
        if self._looks_like_dialog(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_dialog_details(summary_candidates))
            if details:
                return f"弹窗：{details}"
        if self._looks_like_form(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"表单：{details}"
        if self._looks_like_chat(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"聊天：{details}"
        if self._looks_like_navigation(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"导航：{details}"
        if self._looks_like_control(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"控件：{details}"
        if self._looks_like_subject(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"主体：{details}"
        if self._looks_like_chart(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"图表：{details}"
        if self._looks_like_table(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"表格：{details}"
        if self._looks_like_card(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"卡片：{details}"
        if self._looks_like_content(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"内容：{details}"
        if self._looks_like_scene(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                if self._is_too_generic_scene_fact(details):
                    return ""
                return f"画面：{details}"
        if self._looks_like_status(summary_candidates, detail_lines, labels):
            details = self._join_fact_details(detail_lines, fallback=self._extract_visual_details(summary_candidates))
            if details:
                return f"状态：{details}"
        if len(window_title) >= 4 and self._looks_like_login(summary_candidates, detail_lines):
            return f"页面：{window_title}"
        if region_name in {"自动主内容区", "主内容区"} and len(window_title) >= 4 and self._looks_like_page(summary_candidates):
            return f"页面：{window_title}"
        return info

    def _list_prefix_for_event(self, event: TimelineEvent, target_name: str, items: list[str]) -> str:
        if "微信" in target_name:
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
        attributes = event.visual.attributes or {}
        observation = attributes.get("structured_observation") or {}
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

    def _looks_like_dialog(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["弹窗", "对话框", "dialog", "modal"])

    def _looks_like_chart(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["图表", "折线图", "柱状图", "饼图", "趋势图", "chart", "chart_like"])

    def _looks_like_table(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        explicit_tokens = ["表格", "数据表", "table"]
        if any(token in haystack for token in explicit_tokens):
            return True
        return any(token in haystack for token in ["价格列", "库存列", "字段列", "多行数据", "数据行"])

    def _looks_like_card(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["卡片", "card", "缩略图", "推荐卡", "商品卡", "视频卡"])

    def _looks_like_form(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["表单", "登录表单", "验证码", "手机号", "密码", "搜索框"])

    def _looks_like_navigation(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["导航", "页签", "标签导航", "tab", "选中设置页签", "顶部标签"])

    def _looks_like_control(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["按钮", "开关", "下拉", "勾选", "保存按钮", "取消按钮"])

    def _looks_like_ppt(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["ppt", "幻灯片", "缩略图列表", "演示文稿"])

    def _looks_like_chat(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        if any(token in haystack for token in ["登录表单", "验证码", "手机号", "密码"]):
            return False
        return any(token in haystack for token in ["聊天", "联系人", "消息气泡", "输入框", "聊天页面"])

    def _looks_like_subject(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["主体", "图像主体", "主物体", "近景主体"])

    def _looks_like_content(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["文档", "正文", "文章", "ppt", "幻灯片", "要点", "段落", "内容页"])

    def _looks_like_scene(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["视频帧", "主画面", "人物", "字幕", "封面", "插图", "图片", "画面"])

    def _looks_like_status(self, summaries: list[str], detail_lines: list[str], labels: set[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines, " ".join(sorted(labels))]).lower()
        return any(token in haystack for token in ["错误", "异常", "告警", "警告", "失败", "成功", "重新登录", "提示", "loading", "加载"])

    def _looks_like_login(self, summaries: list[str], detail_lines: list[str]) -> bool:
        haystack = " ".join([*summaries, *detail_lines])
        return any(token in haystack for token in ["登录", "手机号", "验证码", "账号", "密码"])

    def _looks_like_page(self, summaries: list[str]) -> bool:
        haystack = " ".join(summaries)
        return any(token in haystack for token in ["页面", "网页", "登录", "设置", "表单", "详情"])

    def _looks_like_sidebar_list_context(self, event: TimelineEvent, *, target_name: str, items: list[str]) -> bool:
        hints = " ".join(
            [
                target_name,
                str(event.summary or ""),
                str(event.visual.summary or ""),
                " ".join(items[:4]),
            ]
        ).lower()
        return any(token in hints for token in ["chat", "slack", "discord", "wechat", "会话", "群", "联系人", "频道", "未读", "私聊", "群聊"])

    def _join_fact_details(self, detail_lines: list[str], *, fallback: list[str]) -> str:
        values = list(detail_lines or []) or [item for item in list(fallback or []) if not self._is_low_value_detail_line(item)]
        cleaned: list[str] = []
        for item in values:
            text = self._trim_info(str(item or "").strip(" ，。,.；;"))
            if not text or self._is_low_value_detail_line(text):
                continue
            if text not in cleaned:
                cleaned.append(text)
        return self._trim_info("，".join(cleaned[:3]))

    def _extract_dialog_details(self, summaries: list[str]) -> list[str]:
        values: list[str] = []
        for summary in summaries:
            if not summary:
                continue
            for piece in re.split(r"[，,；;]", summary):
                text = self._trim_info(piece.strip(" ，。,.；;"))
                if not text:
                    continue
                if any(token in text for token in ["弹窗", "输入框", "按钮", "确认", "取消"]):
                    text = text.replace("包含", "").replace("出现", "")
                    text = text.replace("中央", "中央")
                    if text not in values:
                        values.append(text)
        return values[:3]

    def _extract_visual_details(self, summaries: list[str]) -> list[str]:
        values: list[str] = []
        for summary in summaries:
            if not summary:
                continue
            normalized = summary.replace("主内容是一张", "").replace("主内容是", "").replace("中部是一张", "").replace("中部是", "")
            for piece in re.split(r"[，,；;]", normalized):
                text = self._trim_info(piece.strip(" ，。,.；;"))
                if not text:
                    continue
                if text not in values:
                    values.append(text)
        return values[:3]

    def _build_compact_info_code(self, info: str, *, region: str = "") -> str:
        text = self._trim_info(str(info or "").strip())
        if "：" not in text:
            return ""
        prefix, rest = text.split("：", 1)
        scene_alias = {
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
        }.get(prefix, prefix.lower())
        parts = [part.strip() for part in re.split(r"[，,；;]", rest) if part.strip()]
        compact_parts = parts[:3]
        region_alias = "main"
        if "顶部" in region:
            region_alias = "top"
        elif "左侧" in region:
            region_alias = "left"
        elif "右侧" in region:
            region_alias = "right"
        elif "底部" in region:
            region_alias = "bottom"
        elif "全目标" in region:
            region_alias = "full"
        slots = [f"scn={scene_alias}", f"reg={region_alias}"]
        for index, part in enumerate(compact_parts, start=1):
            slots.append(f"k{index}={part}")
        return "|".join(slots)

    def _should_emit_compact_code(self, info: str) -> bool:
        text = str(info or "").strip()
        if not text or "：" not in text:
            return False
        return not text.startswith(("微信会话列表：", "时间列表：", "左侧列表：", "右侧列表：", "顶部列表：", "底部列表："))

    def _extract_time_labeled_items(self, text: str) -> list[str]:
        normalized = " ".join(str(text or "").split())
        matches = list(re.finditer(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", normalized))
        items: list[str] = []
        for match in matches:
            start = max(0, match.start() - 32)
            prefix = normalized[start : match.start()]
            name = self._clean_list_item_name(prefix)
            if not name:
                continue
            item = f"{name} {match.group(0)}"
            if item not in items:
                items.append(item)
        return items

    def _clean_list_item_name(self, value: str) -> str:
        text = re.sub(r"\[[^\]]*\]", " ", str(value or ""))
        text = re.sub(r"[@＠]\S+", " ", text)
        text = re.sub(r"\b\d+\s*$", " ", text)
        parts = [part for part in re.split(r"\s+", text.strip()) if part]
        parts = [part for part in parts if ":" not in part and "：" not in part]
        if not parts:
            return ""
        name = parts[-1].strip(" ，。,.|丨·-_:：")
        if len(name) < 2:
            return ""
        return self._trim_info(name)

    def compact_short_memory(self, *, task_id: str, timestamp: float) -> Dict[str, Any]:
        short_path = self.short_event_path(task_id=task_id, timestamp=timestamp)
        compact_path = self.compact_segments_path(task_id=task_id, timestamp=timestamp)
        rows = self._read_jsonl(short_path)
        segments = self._build_adjacent_segments(rows)
        compact_path.parent.mkdir(parents=True, exist_ok=True)
        with compact_path.open("w", encoding="utf-8") as output:
            for segment in segments:
                output.write(json.dumps(segment, ensure_ascii=False, sort_keys=True))
                output.write("\n")
        return {
            "task_id": task_id,
            "short_path": str(short_path),
            "compact_path": str(compact_path),
            "source_count": len(rows),
            "segment_count": len(segments),
        }

    def count_short_events(self, *, task_id: str, timestamp: float) -> int:
        path = self.short_event_path(task_id=task_id, timestamp=timestamp)
        if not path.exists():
            return 0
        try:
            with path.open("r", encoding="utf-8") as handle:
                return sum(1 for line in handle if line.strip())
        except OSError:
            return 0

    def _read_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _build_adjacent_segments(self, rows: list[dict]) -> list[dict]:
        segments: list[dict] = []
        current: Optional[dict] = None
        current_key = ""
        for row in rows:
            info = self._trim_info(str(row.get("info") or ""))
            if not info:
                continue
            row_time = str(row.get("time") or "")
            region = self._trim_info(str(row.get("region") or ""))
            key = self._normalize_segment_key(info=info, region=region)
            if current is not None and key == current_key:
                current["to"] = row_time or current["to"]
                current["repeat_count"] = int(current["repeat_count"]) + 1
                continue
            if current is not None:
                segments.append(current)
            current_key = key
            current = {
                "from": row_time,
                "to": row_time,
                "info": info,
                "repeat_count": 1,
            }
            if region:
                current["region"] = region
        if current is not None:
            segments.append(current)
        return segments

    def _normalize_segment_key(self, *, info: str, region: str) -> str:
        return "\n".join([self._normalize_segment_info(region), self._normalize_segment_info(info)])

    def _normalize_segment_info(self, value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _compact_long_summary(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        info = self._trim_info(self._clean_long_info(str(payload.get("summary") or "").strip()))
        if not info:
            return None
        return {
            "from": self._format_timestamp(float(payload.get("window_start") or 0.0)),
            "to": self._format_timestamp(float(payload.get("window_end") or payload.get("window_start") or 0.0)),
            "info": info,
        }

    def _best_event_info(self, event: TimelineEvent) -> str:
        summary = str(event.summary or "").strip()
        text = str(event.text.ocr_text or event.text.normalized_text or "").strip()
        visual_summary = str(event.visual.summary or "").strip()
        for value in [summary, text, visual_summary]:
            if not value:
                continue
            if value.startswith("OCR vision |") or value.startswith("视觉增强已跳过") or value.startswith("视觉增强已触发"):
                continue
            return self._trim_info(value)
        return ""

    def _trim_info(self, value: str) -> str:
        text = " ".join(str(value or "").split())
        if len(text) > 180:
            return text[:177] + "..."
        return text

    def _clean_long_info(self, value: str) -> str:
        parts = []
        for raw in str(value or "").split("；"):
            part = self._trim_info(raw)
            if not part:
                continue
            if part.startswith("视觉增强已跳过") or part.startswith("视觉增强已触发") or part.startswith("OCR vision |"):
                continue
            if part not in parts:
                parts.append(part)
        return "；".join(parts)

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
        if re.search(r"[A-Za-z]\*%[A-Za-z]\*", text):
            return True
        return False

    def _is_low_value_detail_line(self, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return True
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
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
        if cjk_count == 0 and symbol_count >= 2 and ascii_alpha_count < 8:
            return True
        return False

    def _looks_like_visual_noise_summary(self, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return True
        if self._looks_like_gibberish(text):
            return True
        return any(token in text for token in ["无意义字符", "字幕碎片", "乱码", "低质量文本"])

    def _is_too_generic_scene_fact(self, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return True
        generic_markers = [
            "视频主画面",
            "主画面是视频帧",
            "视频帧",
            "主画面",
        ]
        return text in generic_markers

    def _is_low_information_fragment(self, event: TimelineEvent, info: str) -> bool:
        text = str(info or "").strip()
        if not text:
            return True
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            return True
        if self._looks_like_short_fact_label(text):
            return False
        if event.source == "ocr" and "：" not in text and ":" not in text:
            compact = "".join(text.split())
            if len(compact) <= 6:
                return True
            tokens = [token for token in re.split(r"\s+", text) if token]
            if len(tokens) <= 2 and len(text) < 14:
                return True
        return False

    def _is_medium_quality_noise(self, event: TimelineEvent, info: str) -> bool:
        if event.source != "ocr":
            return False
        attributes = event.visual.attributes or {}
        score = float(attributes.get("text_quality_score") or 0.0)
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
        if cjk_count == 0 and symbol_count / max(len(chars), 1) > 0.18:
            return True
        return False

    def _looks_like_short_fact_label(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        return any(token in value for token in ["登录", "设置", "页面", "详情", "弹窗", "表单", "导航", "聊天", "PPT", "列表", "会话", "内容区", "主内容区"])

    def _format_timestamp(self, timestamp: float) -> str:
        return datetime.fromtimestamp(float(timestamp), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
