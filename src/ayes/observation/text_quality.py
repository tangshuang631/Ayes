"""OCR text quality scoring helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional


_READABLE_RE = re.compile(r"[\w\u4e00-\u9fff]", re.UNICODE)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_DIGIT_RE = re.compile(r"\d")


@dataclass(frozen=True)
class TextQuality:
    score: float
    readable_ratio: float
    gibberish_ratio: float
    repeated_symbol_ratio: float
    avg_confidence: float
    char_count: int
    is_noisy: bool


def score_ocr_text(text: str, *, avg_confidence: float = 0.0, block_confidences: Optional[Iterable[float]] = None) -> TextQuality:
    normalized = str(text or "").strip()
    char_count = len(normalized)
    confidences = [float(value) for value in (block_confidences or []) if value is not None]
    if confidences:
        avg_confidence = sum(confidences) / len(confidences)
    avg_confidence = max(0.0, min(float(avg_confidence or 0.0), 1.0))
    if char_count == 0:
        return TextQuality(0.0, 0.0, 1.0, 0.0, avg_confidence, 0, True)

    compact = "".join(normalized.split())
    compact_len = max(len(compact), 1)
    readable_count = len(_READABLE_RE.findall(compact))
    readable_ratio = readable_count / compact_len
    replacement_ratio = compact.count("\ufffd") / compact_len
    symbol_ratio = sum(1 for ch in compact if not _READABLE_RE.match(ch)) / compact_len
    repeated_symbol_ratio = _repeated_symbol_ratio(compact)
    word_signal = min((_word_signal(normalized) / 4.0), 1.0)
    length_signal = min(char_count / 24.0, 1.0)
    random_latin_ratio = _random_latin_ratio(compact)
    mixed_symbol_run_ratio = _mixed_symbol_run_ratio(compact)
    diagnostic_ratio = 0.3 if _looks_like_internal_ocr_diagnostic(normalized) else 0.0

    gibberish_ratio = max(
        0.0,
        min(1.0, replacement_ratio + max(symbol_ratio - 0.18, 0.0) + repeated_symbol_ratio + random_latin_ratio + mixed_symbol_run_ratio + diagnostic_ratio),
    )
    score = (
        avg_confidence * 0.36
        + readable_ratio * 0.26
        + word_signal * 0.18
        + length_signal * 0.12
        - gibberish_ratio * 0.34
        - repeated_symbol_ratio * 0.12
        - mixed_symbol_run_ratio * 0.14
        - diagnostic_ratio * 0.18
    )
    score = round(max(0.0, min(score, 1.0)), 4)
    is_noisy = (
        score < 0.42
        or gibberish_ratio > 0.38
        or replacement_ratio > 0.0
        or _looks_like_internal_ocr_diagnostic(normalized)
        or (avg_confidence < 0.45 and char_count < 24)
    )
    return TextQuality(
        score=score,
        readable_ratio=round(readable_ratio, 4),
        gibberish_ratio=round(gibberish_ratio, 4),
        repeated_symbol_ratio=round(repeated_symbol_ratio, 4),
        avg_confidence=round(avg_confidence, 4),
        char_count=char_count,
        is_noisy=is_noisy,
    )


def _word_signal(text: str) -> int:
    return len(_CJK_RE.findall(text)) + len(_LATIN_WORD_RE.findall(text)) + min(len(_DIGIT_RE.findall(text)), 2)


def _repeated_symbol_ratio(text: str) -> float:
    if not text:
        return 0.0
    repeated = 0
    previous = ""
    streak = 0
    for ch in text:
        if ch == previous:
            streak += 1
        else:
            streak = 1
            previous = ch
        if streak >= 3 and not _READABLE_RE.match(ch):
            repeated += 1
    return repeated / max(len(text), 1)


def _random_latin_ratio(text: str) -> float:
    latin_runs = re.findall(r"[A-Za-z0-9]{5,}", text)
    if not latin_runs:
        return 0.0
    suspicious = 0
    for run in latin_runs:
        has_upper = any(ch.isupper() for ch in run)
        has_lower = any(ch.islower() for ch in run)
        has_digit = any(ch.isdigit() for ch in run)
        vowel_ratio = sum(1 for ch in run.lower() if ch in "aeiou") / max(len(run), 1)
        if (has_upper and has_lower and has_digit) or vowel_ratio < 0.18:
            suspicious += len(run)
    return min(suspicious / max(len(text), 1), 1.0) * 0.55


def _mixed_symbol_run_ratio(text: str) -> float:
    runs = re.findall(r"[A-Za-z0-9_¥$*|]{6,}", text)
    if not runs:
        return 0.0
    suspicious = sum(len(run) for run in runs if any(ch in "_¥$*|" for ch in run))
    return min(suspicious / max(len(text), 1), 1.0) * 0.45


def _looks_like_internal_ocr_diagnostic(text: str) -> bool:
    value = str(text or "")
    return value.startswith("OCR vision |") or "OCR vision | 字符" in value
