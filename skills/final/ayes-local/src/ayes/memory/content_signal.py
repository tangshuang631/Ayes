"""Rank and filter events for user-facing memory answers."""

from __future__ import annotations

import re
from typing import Iterable, List

from ayes.events.models import TimelineEvent
from ayes.observation.text_quality import score_ocr_text


GENERIC_VISUAL_SUMMARY_MARKERS = (
    "多个视频缩略图",
    "视频缩略图展示",
    "播放次数和点赞数",
    "多个缩略图",
    "many thumbnails",
)

LOW_VALUE_EVENT_TYPES = {"vision_skipped", "vision_triggered"}
HIGH_VALUE_EVENT_TYPES = {
    "target_window_changed",
    "window_title_changed",
    "visual_summary",
    "semantic_match",
    "alert_sent",
    "alert_failed",
}


def rank_memory_events(events: Iterable[TimelineEvent], *, question: str = "", limit: int = 5) -> List[TimelineEvent]:
    candidates = [event for event in events if content_signal_score(event, question=question) > 0]
    candidates.sort(key=lambda event: (content_signal_score(event, question=question), event.timestamp), reverse=True)
    return sorted(candidates[:limit], key=lambda event: event.timestamp)


def is_memory_worthy_event(event: TimelineEvent) -> bool:
    return content_signal_score(event) >= 0.45


def content_signal_score(event: TimelineEvent, *, question: str = "") -> float:
    summary = clean_memory_summary(event.summary)
    text = "\n".join([summary, event.text.ocr_text or "", event.text.normalized_text or "", event.visual.summary or ""]).strip()
    if not text and not event.target.window_title:
        return 0.0
    if event.event_type in LOW_VALUE_EVENT_TYPES:
        return 0.0
    if _is_low_information_ocr_summary(summary):
        return 0.0
    if _is_generic_visual_summary(summary):
        return 0.0

    score = 0.0
    if event.event_type in HIGH_VALUE_EVENT_TYPES:
        score += 0.45
    if event.event_type == "target_window_changed":
        score += 0.45
    if event.watch_match.matched:
        score += 0.45
    if event.source in {"tagger", "vision"} and event.event_type == "visual_summary":
        score += 0.25
    if event.source == "file_memory" and event.event_type == "compact_short_memory":
        score += 0.6
    if _has_readable_cjk_or_words(text):
        score += 0.25
    if _contains_specific_title_like_text(text) or (event.event_type == "target_window_changed" and _contains_specific_title_like_text(event.target.window_title)):
        score += 0.35
    if _is_content_identity_question(question):
        if event.source == "file_memory" or event.event_type in {"target_window_changed", "window_title_changed"}:
            score += 0.9
        elif event.event_type == "visual_summary" and not _contains_specific_title_like_text(text):
            score -= 0.45
    if question and _question_tokens_hit(question, text):
        score += 0.2

    if event.source == "ocr":
        quality = score_ocr_text(event.text.ocr_text or summary, avg_confidence=float(event.confidence or 0.0))
        if (quality.is_noisy or quality.score < 0.42) and _looks_like_garbage(text):
            score -= 0.8
        else:
            score += max(min(quality.score, 0.25), 0.2 if _has_readable_cjk_or_words(text) else 0.0)
    if _looks_like_garbage(text):
        score -= 0.9
    return max(score, 0.0)


def clean_memory_summary(value: str) -> str:
    return " ".join(str(value or "").split())


def summarize_memory_event(event: TimelineEvent) -> str:
    summary = clean_memory_summary(event.summary)
    title = clean_memory_summary(event.target.window_title)
    if event.event_type == "target_window_changed" and title:
        return f"窗口标题：{title}"
    if event.event_type == "target_window_changed" and title and title not in summary and len(title) >= 4:
        return f"{summary}（窗口标题：{title}）" if summary else f"窗口标题：{title}"
    return summary or clean_memory_summary(event.visual.summary) or clean_memory_summary(event.text.ocr_text)


def _is_generic_visual_summary(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in GENERIC_VISUAL_SUMMARY_MARKERS)


def _is_low_information_ocr_summary(text: str) -> bool:
    value = str(text or "").strip()
    return (
        value.startswith("OCR 未识别到文本")
        or value.startswith("OCR 低质量文本已降权")
        or value.startswith("OCR vision |")
    )


def _looks_like_garbage(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    if "\uffff" in value or "�" in value:
        return True
    if re.search(r"[A-Za-z]\*|[A-Za-z]{1,3}\d|[<>#%]{2,}", value):
        return True
    chars = [char for char in value if not char.isspace()]
    if len(chars) < 3:
        return True
    useful = sum(1 for char in chars if "\u4e00" <= char <= "\u9fff" or char.isalpha())
    symbols = sum(1 for char in chars if not char.isalnum() and not ("\u4e00" <= char <= "\u9fff"))
    return useful / max(len(chars), 1) < 0.22 or symbols / max(len(chars), 1) > 0.28


def _has_readable_cjk_or_words(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{4,}", str(text or "")))


def _contains_specific_title_like_text(text: str) -> bool:
    value = str(text or "")
    if len(value) < 8:
        return False
    title_markers = ("？", "?", "！", "!", "【", "】", "：", ":", " - ", "_")
    return any(marker in value for marker in title_markers) and _has_readable_cjk_or_words(value)


def _question_tokens_hit(question: str, text: str) -> bool:
    tokens = [token for token in re.split(r"\s+|[，。！？、,.!?]", question) if len(token) >= 2]
    haystack = text.lower()
    return any(token.lower() in haystack for token in tokens)


def _is_content_identity_question(question: str) -> bool:
    value = str(question or "")
    return any(marker in value for marker in ["看了什么", "看的什么", "视频是什么", "文档是什么", "打开了什么", "具体内容", "页面内容"])
