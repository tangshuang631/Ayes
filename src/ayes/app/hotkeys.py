"""Hotkey parsing and guards for local desktop controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HotkeyConfig:
    canonical: str
    modifiers: frozenset[str]
    key: str


_MODIFIER_ALIASES = {
    "cmd": "cmd",
    "command": "cmd",
    "⌘": "cmd",
    "shift": "shift",
    "⇧": "shift",
    "option": "option",
    "alt": "option",
    "⌥": "option",
    "ctrl": "ctrl",
    "control": "ctrl",
    "⌃": "ctrl",
}
_DANGEROUS_HOTKEYS = {
    "cmd+c",
    "cmd+v",
    "cmd+x",
    "cmd+q",
    "cmd+w",
    "cmd+tab",
    "cmd+space",
}


def parse_hotkey(raw: Any) -> HotkeyConfig | None:
    text = str(raw or "").strip().lower()
    if not text:
        return None
    parts = [part.strip() for part in text.replace(" ", "").split("+") if part.strip()]
    modifiers: list[str] = []
    key_parts: list[str] = []
    for part in parts:
        modifier = _MODIFIER_ALIASES.get(part)
        if modifier:
            if modifier not in modifiers:
                modifiers.append(modifier)
        else:
            key_parts.append(part)
    if len(key_parts) != 1:
        raise ValueError("快捷键必须包含一个普通按键")
    key = key_parts[0]
    if len(key) != 1 and not key.startswith("f"):
        raise ValueError("快捷键普通按键只能是单字符或 F1-F20")
    if "cmd" not in modifiers or not ({"shift", "option", "ctrl"} & set(modifiers)):
        raise ValueError("快捷键必须包含 cmd 以及 shift/option/ctrl 中至少一个")
    ordered_modifiers = [item for item in ("cmd", "shift", "option", "ctrl") if item in modifiers]
    canonical = "+".join([*ordered_modifiers, key])
    if canonical in _DANGEROUS_HOTKEYS:
        raise ValueError("该快捷键与系统常用快捷键冲突")
    return HotkeyConfig(canonical=canonical, modifiers=frozenset(ordered_modifiers), key=key)


def should_handle_latest_frame_hotkey(status_payload: dict[str, Any]) -> bool:
    return bool(status_payload.get("has_runner")) and bool(status_payload.get("is_running"))
