"""macOS menu bar control surface for Ayes."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ayes.app.hotkeys import HotkeyConfig, parse_hotkey, should_handle_latest_frame_hotkey
from ayes.config.models import DEFAULT_SAMPLING_INTERVAL_MS, MAX_SAMPLING_INTERVAL_MS, MIN_SAMPLING_INTERVAL_MS

try:
    from AppKit import (
        NSApp,
        NSApplication,
        NSApplicationActivationPolicyAccessory,
        NSAlternateKeyMask,
        NSBackingStoreBuffered,
        NSBezelStyleRounded,
        NSButton,
        NSColor,
        NSCommandKeyMask,
        NSControlKeyMask,
        NSEvent,
        NSFont,
        NSImage,
        NSKeyDownMask,
        NSMakeRect,
        NSMenu,
        NSMenuItem,
        NSPanel,
        NSPasteboard,
        NSPasteboardTypePNG,
        NSPasteboardTypeString,
        NSPopUpButton,
        NSShiftKeyMask,
        NSStatusBar,
        NSSwitchButton,
        NSTextField,
        NSObject,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSTimer
except ImportError:  # pragma: no cover
    NSApp = None
    NSApplication = None
    NSApplicationActivationPolicyAccessory = None
    NSAlternateKeyMask = None
    NSBackingStoreBuffered = None
    NSBezelStyleRounded = None
    NSButton = None
    NSColor = None
    NSCommandKeyMask = None
    NSControlKeyMask = None
    NSEvent = None
    NSFont = None
    NSImage = None
    NSKeyDownMask = None
    NSMakeRect = None
    NSMenu = None
    NSMenuItem = None
    NSPanel = None
    NSPasteboard = None
    NSPasteboardTypePNG = None
    NSPasteboardTypeString = "public.utf8-plain-text"
    NSPopUpButton = None
    NSShiftKeyMask = None
    NSStatusBar = None
    NSSwitchButton = None
    NSTextField = None
    NSObject = object
    NSWindowStyleMaskClosable = None
    NSWindowStyleMaskTitled = None
    NSTimer = None

try:
    from Quartz import AXIsProcessTrusted, CGEventCreateKeyboardEvent, CGEventPost, kCGEventFlagMaskCommand, kCGHIDEventTap
except ImportError:  # pragma: no cover
    AXIsProcessTrusted = None
    CGEventCreateKeyboardEvent = None
    CGEventPost = None
    kCGEventFlagMaskCommand = None
    kCGHIDEventTap = None


@dataclass(frozen=True)
class MenuBarSummary:
    title: str
    icon_glyph: str
    state_line: str
    task_line: str
    target_line: str
    roi_line: str
    recent_line: str
    is_paused: bool
    has_runner: bool
    is_running: bool
    roi_regions: list[dict[str, Any]]
    recent_tasks: list[dict[str, Any]]
    roi_tasks: list[dict[str, Any]]
    task_tree: list[dict[str, Any]]


def _safe_text(value: Any, fallback: str = "未设置") -> str:
    text = str(value or "").strip()
    return text or fallback


def _summarize_target(target: Any) -> str:
    if not isinstance(target, dict):
        return "目标：未设置"
    target_type = _safe_text(target.get("type"), "目标")
    if target_type == "process":
        name = _safe_text(target.get("process_name"), "未知进程")
        return f"目标：进程监控 {name}"
    if target_type == "window":
        title = _safe_text(target.get("window_title"), "未知窗口")
        return f"目标：窗口监控 {title}"
    if target_type == "screen":
        screen_id = _safe_text(target.get("screen_id"), "默认屏幕")
        return f"目标：全屏监控 屏幕 {screen_id}"
    return f"目标：{target_type}"


def _summarize_roi_regions(target: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(target, dict):
        return "ROI：全目标", []
    regions = [
        item
        for item in list(target.get("regions") or [])
        if isinstance(item, dict) and item.get("enabled", True) is not False
    ]
    if not regions:
        return "ROI：全目标", []
    names = [str(item.get("name") or item.get("region_id") or "ROI") for item in regions[:4]]
    suffix = f" 等 {len(regions)} 个" if len(regions) > 4 else ""
    return f"ROI：{' / '.join(names)}{suffix}", regions


def build_menu_bar_summary(payload: dict[str, Any]) -> MenuBarSummary:
    is_paused = bool(payload.get("is_paused"))
    has_runner = bool(payload.get("has_runner"))
    is_running = bool(payload.get("is_running"))
    task_context = payload.get("task_context") or {}
    recent_tasks = list(task_context.get("recent_tasks") or [])
    task_tree = list(task_context.get("task_tree") or [])
    task_id = _safe_text(payload.get("task_id"), "无任务")
    target_line = _summarize_target(payload.get("target"))
    roi_line, roi_regions = _summarize_roi_regions(payload.get("target"))
    if not has_runner:
        title = "Ayes·Idle"
        icon_glyph = "◌"
        state_line = "空闲"
    elif is_paused:
        title = "Ayes·Paused"
        icon_glyph = "◐"
        state_line = "已暂停"
    elif is_running:
        title = "Ayes·Live"
        icon_glyph = "◉"
        state_line = "监控中"
    else:
        title = "Ayes·Ready"
        icon_glyph = "◎"
        state_line = "就绪"
    latest_key_event = payload.get("latest_key_event") or {}
    last_match_at = payload.get("last_match_at")
    if isinstance(latest_key_event, dict) and latest_key_event.get("summary"):
        recent_line = f"最近：{_safe_text(latest_key_event.get('summary'))}"
    elif last_match_at:
        recent_line = f"最近命中：{int(float(last_match_at))}"
    else:
        recent_line = "最近：暂无"
    return MenuBarSummary(
        title=title,
        icon_glyph=icon_glyph,
        state_line=state_line,
        task_line=f"任务：{task_id}",
        target_line=target_line,
        roi_line=roi_line,
        recent_line=recent_line,
        is_paused=is_paused,
        has_runner=has_runner,
        is_running=is_running,
        roi_regions=roi_regions,
        recent_tasks=recent_tasks[:5],
        roi_tasks=[task for task in recent_tasks if isinstance(task, dict) and task.get("roi")],
        task_tree=task_tree,
    )


def _fallback_status_title(summary: MenuBarSummary) -> str:
    return summary.icon_glyph


def _set_status_button_icon(status_item: Any, summary: MenuBarSummary) -> None:  # pragma: no cover - AppKit runtime
    button = status_item.button()
    if button is None:
        return
    button.setImage_(None)
    button.setTitle_(_fallback_status_title(summary))


def _request_json(base_url: str, path: str, *, method: str = "GET") -> dict:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _post_json(base_url: str, path: str, payload: dict[str, Any]) -> dict:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _recent_task_title(task: dict[str, Any]) -> str:
    task_name = _safe_text(task.get("display_name"), "") or _safe_text(task.get("task_id"), "未知任务")
    roi = task.get("roi") if isinstance(task.get("roi"), dict) else {}
    roi_name = _safe_text(roi.get("roi_name"), "") if roi else ""
    if roi_name:
        return f"{task_name} · ROI · {roi_name}"
    target = task.get("target") if isinstance(task.get("target"), dict) else {}
    target_bits = _task_target_title_bits(target)
    if target_bits:
        return " · ".join([task_name] + target_bits)
    mode = _safe_text(task.get("mode"), "")
    if mode:
        return f"{task_name} · {mode}"
    return task_name


def _task_target_title_bits(target: dict[str, Any]) -> list[str]:
    target_type = _safe_text(target.get("type"), "")
    if target_type == "screen":
        return ["全屏监控", f"屏幕 {_safe_text(target.get('screen_id'), '默认')}"]
    if target_type == "process":
        bits = ["进程监控"]
        process_name = _safe_text(target.get("process_name"), "未知进程")
        if process_name:
            bits.append(process_name)
        detail = _target_detail_text(target)
        if detail:
            bits.append(detail)
        return bits
    if target_type == "window":
        bits = ["窗口监控"]
        detail = _target_detail_text(target) or _safe_text(target.get("window_id"), "")
        if detail:
            bits.append(detail)
        return bits
    return []


def _target_detail_text(target: dict[str, Any]) -> str:
    for key in ["window_title", "title", "target_label", "process_id"]:
        value = str(target.get(key) or "").strip()
        if value:
            return value[:36]
    return ""


def _format_interval_seconds(interval_ms: int) -> str:
    seconds = float(interval_ms) / 1000.0
    if seconds.is_integer():
        return str(int(seconds))
    return f"{seconds:.3f}".rstrip("0").rstrip(".")


def _parse_interval_seconds(raw: Any) -> int:
    try:
        interval_sec = float(str(raw or "").strip())
    except ValueError as exc:
        raise ValueError("采样间隔必须是数字") from exc
    interval_ms = int(round(interval_sec * 1000))
    if interval_ms < MIN_SAMPLING_INTERVAL_MS or interval_ms > MAX_SAMPLING_INTERVAL_MS:
        raise ValueError("采样间隔必须在 0.5 秒到 3600 秒之间")
    return interval_ms


def _menubar_log(message: str, **metadata: Any) -> None:  # pragma: no cover - runtime diagnostics
    payload = {"ts": round(time.time(), 3), "message": message, **metadata}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _objc_class_name(value: Any) -> str:  # pragma: no cover - runtime diagnostics
    if value is None:
        return "None"
    try:
        return str(value.className())
    except Exception:
        return type(value).__name__


def _status_item_debug_payload(status_item: Any) -> dict[str, Any]:  # pragma: no cover - runtime diagnostics
    if status_item is None:
        return {"status_item": "None"}
    button = None
    try:
        button = status_item.button()
    except Exception as exc:
        return {"status_item": _objc_class_name(status_item), "button_error": str(exc)}
    payload: dict[str, Any] = {
        "status_item": _objc_class_name(status_item),
        "button": _objc_class_name(button),
    }
    try:
        payload["length"] = float(status_item.length())
    except Exception:
        pass
    if button is not None:
        try:
            payload["title"] = str(button.title())
        except Exception:
            pass
        try:
            payload["has_image"] = button.image() is not None
        except Exception:
            pass
        try:
            frame = button.frame()
            payload["button_frame"] = {
                "x": float(frame.origin.x),
                "y": float(frame.origin.y),
                "w": float(frame.size.width),
                "h": float(frame.size.height),
            }
        except Exception:
            pass
    return payload


def _resolve_screenshot_path(raw_path: str, data_dir_payload: dict[str, Any]) -> str:
    path = str(raw_path or "").strip()
    if not path:
        return ""
    if path.startswith("/runtime/"):
        relative = path.removeprefix("/runtime/")
    elif path.startswith("runtime/"):
        relative = path.removeprefix("runtime/")
    else:
        return path
    data_dir = str(data_dir_payload.get("data_dir") or "").strip()
    if not data_dir:
        return path
    return str(Path(data_dir) / relative)


def _format_hotkey_action_message(result: str) -> str:
    messages = {
        "copied": "已复制并粘贴最新采样图",
        "not_running": "当前没有正在监控的任务",
        "missing_screenshot": "没有找到最新采样图",
        "missing_file": "最新采样图文件不存在",
        "copy_failed": "复制最新采样图失败",
        "paste_failed": "模拟粘贴失败，请检查辅助功能权限",
    }
    return messages.get(result, "快捷键动作失败")


def _make_label(text: str, *, x: int, y: int, w: int, h: int = 22, bold: bool = False):  # pragma: no cover - UI runtime
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(x, y, w, h))
    if bold:
        label.setFont_(NSFont.boldSystemFontOfSize_(13))
    else:
        label.setFont_(NSFont.systemFontOfSize_(13))
    label.setTextColor_(NSColor.blackColor())
    return label


def _make_muted_label(text: str, *, x: int, y: int, w: int, h: int = 22):  # pragma: no cover - UI runtime
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(x, y, w, h))
    label.setFont_(NSFont.systemFontOfSize_(12))
    label.setTextColor_(NSColor.grayColor())
    return label


def _make_text_field(text: str, *, x: int, y: int, w: int, h: int = 28):  # pragma: no cover - UI runtime
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    field.setStringValue_(text)
    field.setBezeled_(True)
    field.setBezelStyle_(NSBezelStyleRounded)
    field.setFont_(NSFont.systemFontOfSize_(13))
    return field


def _render_recorded_hotkey_label(value: str) -> str:
    return str(value or "").strip()


def _record_hotkey_from_event(event: Any) -> str:
    chars = str(event.charactersIgnoringModifiers() or "")
    if chars == "\x1b":
        return ""
    flags = int(event.modifierFlags())
    parts: list[str] = []
    if flags & int(NSCommandKeyMask):
        parts.append("cmd")
    if flags & int(NSShiftKeyMask):
        parts.append("shift")
    if flags & int(NSAlternateKeyMask):
        parts.append("option")
    if flags & int(NSControlKeyMask):
        parts.append("ctrl")
    key = chars.lower().strip()
    if not key:
        raise ValueError("请按下一个完整快捷键")
    return parse_hotkey("+".join([*parts, key])).canonical


def _make_button(text: str, *, x: int, y: int, w: int, h: int = 30):  # pragma: no cover - UI runtime
    button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    button.setTitle_(text)
    button.setBezelStyle_(NSBezelStyleRounded)
    button.setFont_(NSFont.systemFontOfSize_(13))
    return button


def _event_matches_hotkey(event: Any, hotkey: HotkeyConfig) -> bool:  # pragma: no cover - UI runtime
    chars = str(event.charactersIgnoringModifiers() or "").lower()
    if chars != hotkey.key.lower():
        return False
    flags = int(event.modifierFlags())
    required_masks = {
        "cmd": int(NSCommandKeyMask),
        "shift": int(NSShiftKeyMask),
        "option": int(NSAlternateKeyMask),
        "ctrl": int(NSControlKeyMask),
    }
    for modifier in hotkey.modifiers:
        if not (flags & required_masks[modifier]):
            return False
    return True


def _copy_png_to_pasteboard(image_path: str) -> None:  # pragma: no cover - macOS integration
    if not Path(image_path).exists():
        raise FileNotFoundError(image_path)
    image = NSImage.alloc().initWithContentsOfFile_(image_path)
    if image is None:
        raise RuntimeError("无法读取最新采样图")
    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    if not pasteboard.writeObjects_([image]):
        raise RuntimeError("写入剪贴板失败")


def _copy_text_to_pasteboard(text: str) -> None:  # pragma: no cover - macOS integration
    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    if not pasteboard.setString_forType_(text, NSPasteboardTypeString):
        raise RuntimeError("写入剪贴板失败")


def _paste_from_clipboard() -> None:  # pragma: no cover - macOS integration
    if CGEventCreateKeyboardEvent is None or CGEventPost is None:
        raise RuntimeError("当前环境不支持模拟粘贴")
    if AXIsProcessTrusted is not None and not AXIsProcessTrusted():
        raise PermissionError("Ayes 菜单栏进程没有 macOS 辅助功能权限")
    keycode_v = 9
    key_down = CGEventCreateKeyboardEvent(None, keycode_v, True)
    key_up = CGEventCreateKeyboardEvent(None, keycode_v, False)
    key_down.setFlags_(kCGEventFlagMaskCommand)
    key_up.setFlags_(kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, key_down)
    CGEventPost(kCGHIDEventTap, key_up)


class _MenuBarController(NSObject):  # pragma: no cover - macOS UI runtime
    def initWithBaseURL_(self, base_url: str):
        self = self.init()
        if self is None:
            return None
        self.base_url = base_url.rstrip("/")
        self.status_item = None
        self.menu = None
        self.state_item = None
        self.task_item = None
        self.target_item = None
        self.roi_item = None
        self.recent_item = None
        self.recent_task_items: list[Any] = []
        self.recent_task_separator = None
        self.roi_task_separator = None
        self.roi_task_items: list[Any] = []
        self.pause_item = None
        self.resume_item = None
        self.add_roi_item = None
        self.paste_latest_item = None
        self.settings_item = None
        self.open_item = None
        self.quit_item = None
        self.settings_panel = None
        self.settings_interval_field = None
        self.settings_quality_popup = None
        self.settings_save_ocr_checkbox = None
        self.settings_hotkey_field = None
        self.settings_context_hotkey_field = None
        self.settings_memory_compact_field = None
        self.settings_error_label = None
        self.settings_capturing_hotkey = None
        self.settings_hotkey_capture_monitor = None
        self.hotkey_monitor = None
        self.current_hotkey = None
        self.context_hotkey_monitor = None
        self.current_context_hotkey = None
        self.current_context_prompt = "Ayes context mode"
        self._flash_timer = None
        return self

    def applicationDidFinishLaunching_(self, notification):
        status_bar = NSStatusBar.systemStatusBar()
        _menubar_log("status_bar_resolved", status_bar=_objc_class_name(status_bar))
        self.status_item = status_bar.statusItemWithLength_(24)
        _menubar_log("status_item_created", **_status_item_debug_payload(self.status_item))
        self.menu = NSMenu.alloc().init()
        self.state_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("状态：未读取", None, "")
        self.state_item.setEnabled_(False)
        self.task_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("任务：- ", None, "")
        self.task_item.setEnabled_(False)
        self.target_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("目标：-", None, "")
        self.target_item.setEnabled_(False)
        self.roi_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("ROI：-", None, "")
        self.roi_item.setEnabled_(False)
        self.recent_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("最近：-", None, "")
        self.recent_item.setEnabled_(False)
        self.pause_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("暂停监控", "pauseAll:", "")
        self.resume_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("继续上次的监控", "resumeAll:", "")
        self.add_roi_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("添加 / 管理 ROI...", "openRoiEditor:", "")
        self.paste_latest_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("复制并粘贴最新采样图", "copyLatestFrameAndPaste:", "")
        self.open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("打开数据目录", "openDataDir:", "")
        self.settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("设置...", "openSettings:", "")
        self.quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("退出控制面", "quitApp:", "")
        self.menu.addItem_(self.state_item)
        self.menu.addItem_(self.task_item)
        self.menu.addItem_(self.target_item)
        self.menu.addItem_(self.roi_item)
        self.menu.addItem_(self.recent_item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.pause_item)
        self.menu.addItem_(self.resume_item)
        self.menu.addItem_(self.add_roi_item)
        self.menu.addItem_(self.paste_latest_item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.open_item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.settings_item)
        self.menu.addItem_(self.quit_item)
        self.status_item.setMenu_(self.menu)
        _menubar_log("status_item_menu_attached", **_status_item_debug_payload(self.status_item))
        self.refreshStatus_(None)
        self._refresh_hotkey_registration()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(3.0, self, "refreshStatus:", None, True)

    def _set_recent_task_items(self, tasks: Iterable[dict[str, Any]]) -> None:
        if self.recent_task_separator is not None:
            try:
                self.menu.removeItem_(self.recent_task_separator)
            except Exception:
                pass
            self.recent_task_separator = None
        for item in self.recent_task_items:
            try:
                self.menu.removeItem_(item)
            except Exception:
                pass
        self.recent_task_items = []
        if self.roi_task_separator is not None:
            try:
                self.menu.removeItem_(self.roi_task_separator)
            except Exception:
                pass
            self.roi_task_separator = None
        for item in self.roi_task_items:
            try:
                self.menu.removeItem_(item)
            except Exception:
                pass
        self.roi_task_items = []
        tasks = list(tasks)
        if not tasks:
            return
        self.recent_task_separator = NSMenuItem.separatorItem()
        self.menu.addItem_(self.recent_task_separator)
        for task in tasks:
            title = _recent_task_title(task)
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "switchTask:", "")
            item.setRepresentedObject_(task.get("task_id"))
            if task.get("is_current"):
                item.setState_(1)
            self.menu.addItem_(item)
            self.recent_task_items.append(item)
            for child in list(task.get("children") or []):
                child_title = _recent_task_title(child)
                child_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(f"  └ {child_title}", "switchTask:", "")
                child_item.setRepresentedObject_(child.get("task_id"))
                if child.get("is_current"):
                    child_item.setState_(1)
                self.menu.addItem_(child_item)
                self.roi_task_items.append(child_item)

    def _request_status(self) -> dict:
        payload = _request_json(self.base_url, "/api/status")
        payload.update(_request_json(self.base_url, "/api/control/status"))
        return payload

    def _request_tasks(self) -> list[dict[str, Any]]:
        payload = _request_json(self.base_url, "/api/tasks")
        return list(payload.get("items") or [])

    def refreshStatus_(self, timer):
        try:
            summary = build_menu_bar_summary(self._request_status())
            tasks = self._request_tasks()
        except Exception:
            self.status_item.button().setTitle_("?")
            _menubar_log("status_refresh_failed", **_status_item_debug_payload(self.status_item))
            return
        _set_status_button_icon(self.status_item, summary)
        _menubar_log("status_refreshed", state=summary.state_line, **_status_item_debug_payload(self.status_item))
        self.state_item.setTitle_(f"状态：{summary.state_line}")
        self.task_item.setTitle_(summary.task_line)
        self.target_item.setTitle_(summary.target_line)
        self.roi_item.setTitle_(summary.roi_line)
        self.recent_item.setTitle_(summary.recent_line)
        self.pause_item.setEnabled_(summary.has_runner and (not summary.is_paused))
        self.resume_item.setEnabled_(summary.has_runner and summary.is_paused)
        self.add_roi_item.setEnabled_(summary.has_runner)
        self.paste_latest_item.setEnabled_(summary.has_runner and summary.is_running)
        self.open_item.setEnabled_(True)
        self.settings_item.setEnabled_(True)
        self._set_recent_task_items(tasks)
        self._refresh_hotkey_registration()

    def _refresh_hotkey_registration(self) -> None:
        try:
            settings_payload = _request_json(self.base_url, "/api/control/settings")
            settings = settings_payload.get("settings") or {}
            hotkey = parse_hotkey(settings.get("latest_frame_hotkey"))
            context_hotkey = parse_hotkey(settings.get("monitor_context_hotkey"))
            context_prompt = str(settings.get("monitor_context_prompt") or "Ayes context mode").strip() or "Ayes context mode"
        except Exception:
            hotkey = None
            context_hotkey = None
            context_prompt = "Ayes context mode"
        if hotkey == self.current_hotkey:
            pass
        else:
            if self.hotkey_monitor is not None:
                NSEvent.removeMonitor_(self.hotkey_monitor)
                _menubar_log("hotkey_unregistered", hotkey=getattr(self.current_hotkey, "canonical", ""))
                self.hotkey_monitor = None
            self.current_hotkey = hotkey
            if hotkey is None:
                _menubar_log("hotkey_disabled")
            else:
                def _handler(event):
                    try:
                        if _event_matches_hotkey(event, hotkey):
                            _menubar_log("hotkey_matched", hotkey=hotkey.canonical)
                            self.copyLatestFrameAndPaste_(None)
                            return None
                    except Exception as exc:
                        _menubar_log("hotkey_handler_failed", error=str(exc))
                        return event
                    return event

                self.hotkey_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSKeyDownMask, _handler)
                trusted = bool(AXIsProcessTrusted()) if AXIsProcessTrusted is not None else None
                _menubar_log("hotkey_registered", hotkey=hotkey.canonical, accessibility_trusted=trusted)

        if context_hotkey == self.current_context_hotkey and context_prompt == self.current_context_prompt:
            return
        if self.context_hotkey_monitor is not None:
            NSEvent.removeMonitor_(self.context_hotkey_monitor)
            _menubar_log("context_hotkey_unregistered", hotkey=getattr(self.current_context_hotkey, "canonical", ""))
            self.context_hotkey_monitor = None
        self.current_context_hotkey = context_hotkey
        self.current_context_prompt = context_prompt
        if context_hotkey is None:
            _menubar_log("context_hotkey_disabled")
            return

        def _context_handler(event):
            try:
                if _event_matches_hotkey(event, context_hotkey):
                    _menubar_log("context_hotkey_matched", hotkey=context_hotkey.canonical)
                    self.pasteMonitorContextPrompt_(None)
                    return None
            except Exception as exc:
                _menubar_log("context_hotkey_handler_failed", error=str(exc))
                return event
            return event

        self.context_hotkey_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSKeyDownMask, _context_handler)
        trusted = bool(AXIsProcessTrusted()) if AXIsProcessTrusted is not None else None
        _menubar_log("context_hotkey_registered", hotkey=context_hotkey.canonical, accessibility_trusted=trusted)

    def _flash_status_title(self, message: str) -> None:
        if self.status_item is None:
            return
        try:
            self.status_item.button().setTitle_(f"◉ {message}")
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1.8, self, "refreshStatus:", None, False)
        except Exception:
            pass

    def copyLatestFrameAndPaste_(self, sender):
        result = "unknown"
        try:
            control_status = _request_json(self.base_url, "/api/control/status")
            if not should_handle_latest_frame_hotkey(control_status):
                result = "not_running"
                self._flash_status_title(_format_hotkey_action_message(result))
                _menubar_log("paste_latest_skipped", result=result, control_status=control_status)
                return
            screenshot = _request_json(self.base_url, "/api/hotkey/latest-frame", method="POST")
            raw_path = str(screenshot.get("path") or "").strip()
            if not raw_path:
                result = "missing_screenshot"
                self._flash_status_title(_format_hotkey_action_message(result))
                _menubar_log("paste_latest_skipped", result=result, screenshot=screenshot)
                return
            data_dir = _request_json(self.base_url, "/api/control/open-data-dir")
            image_path = _resolve_screenshot_path(raw_path, data_dir)
            _menubar_log("paste_latest_copying", raw_path=raw_path, image_path=image_path)
            _copy_png_to_pasteboard(image_path)
            _paste_from_clipboard()
            result = "copied"
            self._flash_status_title(_format_hotkey_action_message(result))
            _menubar_log("paste_latest_completed", result=result, image_path=image_path)
        except FileNotFoundError as exc:
            result = "missing_file"
            self._flash_status_title(_format_hotkey_action_message(result))
            _menubar_log("paste_latest_failed", result=result, error=str(exc))
        except PermissionError as exc:
            result = "paste_failed"
            self._flash_status_title(_format_hotkey_action_message(result))
            _menubar_log("paste_latest_failed", result=result, error=str(exc))
        except Exception as exc:
            result = "copy_failed"
            self._flash_status_title(_format_hotkey_action_message(result))
            _menubar_log("paste_latest_failed", result=result, error=str(exc))
            return

    def pasteMonitorContextPrompt_(self, sender):
        try:
            _copy_text_to_pasteboard(self.current_context_prompt or "Ayes context mode")
            _paste_from_clipboard()
            self._flash_status_title("已粘贴 Ayes 提问提示")
            _menubar_log("context_prompt_pasted", prompt=self.current_context_prompt or "Ayes context mode")
        except Exception as exc:
            self._flash_status_title("粘贴提问提示失败")
            _menubar_log("context_prompt_paste_failed", error=str(exc))

    def pauseAll_(self, sender):
        try:
            _request_json(self.base_url, "/api/control/pause-all", method="POST")
        finally:
            self.refreshStatus_(None)

    def resumeAll_(self, sender):
        try:
            _request_json(self.base_url, "/api/control/resume-all", method="POST")
        finally:
            self.refreshStatus_(None)

    def openRoiEditor_(self, sender):
        # ROI editing still needs the visual selector until the native selector ships.
        subprocess.run(["open", f"{self.base_url}/#roi-editor"], check=False)

    def openSettings_(self, sender):
        try:
            status_payload = self._request_status()
            sampling_payload = _request_json(self.base_url, "/api/control/sampling")
            settings_payload = _request_json(self.base_url, "/api/control/settings")
        except Exception as exc:
            self._show_settings_panel(
                task_id="读取失败",
                target_line="无法连接本地 Ayes 服务",
                interval_ms=DEFAULT_SAMPLING_INTERVAL_MS,
                quality="standard",
                save_ocr_screenshots=False,
                latest_frame_hotkey="",
                monitor_context_hotkey="",
                memory_compact_every_n_events=500,
                error=str(exc),
            )
            return
        sampling = sampling_payload.get("sampling") or {}
        settings = settings_payload.get("settings") or {}
        memory_policy = {}
        task_id = str(status_payload.get("task_id") or "")
        if task_id:
            try:
                memory_policy = (_request_json(self.base_url, f"/api/tasks/{task_id}/memory-policy").get("memory_policy") or {})
            except Exception:
                memory_policy = {}
        interval_ms = int(sampling.get("interval_ms") or DEFAULT_SAMPLING_INTERVAL_MS)
        summary = build_menu_bar_summary(status_payload)
        self._show_settings_panel(
            task_id=_safe_text(task_id, "无任务"),
            target_line=summary.target_line,
            interval_ms=interval_ms,
            quality=str(sampling.get("quality") or "standard"),
            save_ocr_screenshots=bool(sampling.get("save_ocr_screenshots", False)),
            latest_frame_hotkey=str(settings.get("latest_frame_hotkey") or ""),
            monitor_context_hotkey=str(settings.get("monitor_context_hotkey") or ""),
            memory_compact_every_n_events=int(memory_policy.get("memory_compact_every_n_events") or 500),
            error="",
        )

    def _set_hotkey_capture_mode(self, field_name: str | None) -> None:
        if self.settings_hotkey_capture_monitor is not None:
            NSEvent.removeMonitor_(self.settings_hotkey_capture_monitor)
            self.settings_hotkey_capture_monitor = None
        self.settings_capturing_hotkey = field_name
        capture_text = "请按快捷键，Esc 清空"
        if self.settings_error_label is not None:
            self.settings_error_label.setStringValue_(capture_text if field_name else "")
            self.settings_error_label.setTextColor_(NSColor.grayColor())
        mapping = {
            "latest_frame_hotkey": self.settings_hotkey_field,
            "monitor_context_hotkey": self.settings_context_hotkey_field,
        }
        for key, field in mapping.items():
            if field is None:
                continue
            field.setEditable_(False)
            field.setSelectable_(False)
            if field_name == key:
                field.setStringValue_(capture_text)
        if field_name:
            def _capture_handler(event):
                self._handle_settings_hotkey_capture(event)
                return None

            self.settings_hotkey_capture_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSKeyDownMask, _capture_handler)

    def beginHotkeyCapture_(self, sender):
        field_name = str(sender.representedObject() or "")
        if field_name not in {"latest_frame_hotkey", "monitor_context_hotkey"}:
            return
        self._set_hotkey_capture_mode(field_name)

    def _apply_recorded_hotkey(self, field_name: str, value: str) -> None:
        field = self.settings_hotkey_field if field_name == "latest_frame_hotkey" else self.settings_context_hotkey_field
        if field is None:
            return
        field.setStringValue_(_render_recorded_hotkey_label(value))
        self._set_hotkey_capture_mode(None)

    def _handle_settings_hotkey_capture(self, event: Any) -> bool:
        field_name = str(self.settings_capturing_hotkey or "")
        if not field_name:
            return False
        try:
            canonical = _record_hotkey_from_event(event)
        except Exception as exc:
            if self.settings_error_label is not None:
                self.settings_error_label.setStringValue_(str(exc))
                self.settings_error_label.setTextColor_(NSColor.systemRedColor())
            return True
        self._apply_recorded_hotkey(field_name, canonical)
        return True

    def _show_settings_panel(
        self,
        *,
        task_id: str,
        target_line: str,
        interval_ms: int,
        quality: str,
        save_ocr_screenshots: bool,
        latest_frame_hotkey: str,
        monitor_context_hotkey: str,
        memory_compact_every_n_events: int,
        error: str,
    ) -> None:
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 480, 540),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        panel.setTitle_("Ayes 设置")
        panel.setBackgroundColor_(NSColor.whiteColor())
        content = panel.contentView()

        content.addSubview_(_make_label("Ayes 设置", x=24, y=492, w=220, h=28, bold=True))
        content.addSubview_(_make_muted_label("桌面控制面板，配置直接写入当前任务。", x=24, y=468, w=410))
        content.addSubview_(_make_label(f"任务：{task_id}", x=24, y=432, w=420))
        content.addSubview_(_make_label(target_line, x=24, y=406, w=420))
        content.addSubview_(_make_label("采样间隔", x=24, y=366, w=100, bold=True))
        self.settings_interval_field = _make_text_field(_format_interval_seconds(interval_ms), x=124, y=362, w=96)
        content.addSubview_(self.settings_interval_field)
        content.addSubview_(_make_label("秒", x=230, y=366, w=30))
        content.addSubview_(_make_muted_label("范围 0.5 秒到 3600 秒。默认 6 秒，保存后截图、OCR、变化检测同步更新。", x=24, y=336, w=430))

        content.addSubview_(_make_label("采样质量", x=24, y=298, w=100, bold=True))
        self.settings_quality_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(124, 292, 180, 30), False)
        quality_items = [
            ("原始质量", "original"),
            ("标准质量 · 1920", "standard"),
            ("节省空间 · 1280", "space_saver"),
            ("极省空间 · 960", "ultra_saver"),
        ]
        for title, represented in quality_items:
            self.settings_quality_popup.addItemWithTitle_(title)
            self.settings_quality_popup.lastItem().setRepresentedObject_(represented)
            if represented == quality:
                self.settings_quality_popup.selectItem_(self.settings_quality_popup.lastItem())
        content.addSubview_(self.settings_quality_popup)

        self.settings_save_ocr_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(120, 252, 260, 28))
        self.settings_save_ocr_checkbox.setButtonType_(NSSwitchButton)
        self.settings_save_ocr_checkbox.setTitle_("保存事件证据截图")
        self.settings_save_ocr_checkbox.setState_(1 if save_ocr_screenshots else 0)
        content.addSubview_(self.settings_save_ocr_checkbox)
        content.addSubview_(_make_muted_label("关闭后只保留记忆、事件和日志；手动导出/告警证据可再临时保存。", x=24, y=224, w=430))

        content.addSubview_(_make_label("记忆合并", x=24, y=186, w=100, bold=True))
        self.settings_memory_compact_field = _make_text_field(str(memory_compact_every_n_events), x=124, y=182, w=96)
        content.addSubview_(self.settings_memory_compact_field)
        content.addSubview_(_make_label("条", x=230, y=186, w=30))
        content.addSubview_(_make_muted_label("每 N 条短期记忆合并相邻重复段；范围 100-5000，默认 500。", x=24, y=156, w=430))

        content.addSubview_(_make_label("截图快捷键", x=24, y=120, w=100, bold=True))
        self.settings_hotkey_field = _make_text_field(latest_frame_hotkey, x=124, y=116, w=150)
        self.settings_hotkey_field.setEditable_(False)
        self.settings_hotkey_field.setSelectable_(False)
        content.addSubview_(self.settings_hotkey_field)
        hotkey_record_button = _make_button("录制", x=284, y=116, w=54, h=28)
        hotkey_record_button.setTarget_(self)
        hotkey_record_button.setAction_("beginHotkeyCapture:")
        hotkey_record_button.setRepresentedObject_("latest_frame_hotkey")
        content.addSubview_(hotkey_record_button)
        content.addSubview_(_make_muted_label("例：cmd+shift+9。仅菜单栏运行且监控中生效；留空关闭。", x=24, y=90, w=430))

        content.addSubview_(_make_label("提问快捷键", x=24, y=58, w=100, bold=True))
        self.settings_context_hotkey_field = _make_text_field(monitor_context_hotkey, x=124, y=54, w=150)
        self.settings_context_hotkey_field.setEditable_(False)
        self.settings_context_hotkey_field.setSelectable_(False)
        content.addSubview_(self.settings_context_hotkey_field)
        context_record_button = _make_button("录制", x=284, y=54, w=54, h=28)
        context_record_button.setTarget_(self)
        context_record_button.setAction_("beginHotkeyCapture:")
        context_record_button.setRepresentedObject_("monitor_context_hotkey")
        content.addSubview_(context_record_button)
        content.addSubview_(_make_muted_label("例：cmd+shift+8。粘贴短提示：Ayes context mode。", x=24, y=28, w=430))

        self.settings_error_label = _make_muted_label(error, x=24, y=6, w=280)
        if error:
            self.settings_error_label.setTextColor_(NSColor.systemRedColor())
        content.addSubview_(self.settings_error_label)

        cancel_button = _make_button("取消", x=306, y=10, w=76)
        cancel_button.setTarget_(self)
        cancel_button.setAction_("cancelSettings:")
        content.addSubview_(cancel_button)

        save_button = _make_button("保存", x=392, y=10, w=66)
        save_button.setTarget_(self)
        save_button.setAction_("saveSettings:")
        save_button.setKeyEquivalent_("\r")
        content.addSubview_(save_button)

        self.settings_panel = panel
        panel.setInitialFirstResponder_(self.settings_interval_field)
        NSApp.activateIgnoringOtherApps_(True)
        panel.center()
        panel.makeKeyAndOrderFront_(None)

    def cancelSettings_(self, sender):
        if self.settings_panel is not None:
            self.settings_panel.close()
        self.settings_panel = None
        self.settings_capturing_hotkey = None
        if self.settings_hotkey_capture_monitor is not None:
            NSEvent.removeMonitor_(self.settings_hotkey_capture_monitor)
            self.settings_hotkey_capture_monitor = None

    def saveSettings_(self, sender):
        if self.settings_interval_field is None:
            return
        try:
            if self.settings_capturing_hotkey:
                raise ValueError("请先完成快捷键录制")
            interval_ms = _parse_interval_seconds(self.settings_interval_field.stringValue())
            latest_frame_hotkey = str(self.settings_hotkey_field.stringValue() if self.settings_hotkey_field is not None else "")
            monitor_context_hotkey = str(self.settings_context_hotkey_field.stringValue() if self.settings_context_hotkey_field is not None else "")
            quality = "standard"
            if self.settings_quality_popup is not None and self.settings_quality_popup.selectedItem() is not None:
                quality = str(self.settings_quality_popup.selectedItem().representedObject() or "standard")
            save_ocr_screenshots = bool(self.settings_save_ocr_checkbox.state()) if self.settings_save_ocr_checkbox is not None else False
            _post_json(self.base_url, "/api/control/sampling", {"interval_ms": interval_ms, "quality": quality, "save_ocr_screenshots": save_ocr_screenshots})
            _post_json(
                self.base_url,
                "/api/control/settings",
                {"latest_frame_hotkey": latest_frame_hotkey, "monitor_context_hotkey": monitor_context_hotkey},
            )
            status_payload = self._request_status()
            task_id = str(status_payload.get("task_id") or "")
            if task_id and self.settings_memory_compact_field is not None:
                compact_every = int(str(self.settings_memory_compact_field.stringValue()).strip())
                if compact_every < 100 or compact_every > 5000:
                    raise ValueError("记忆合并阈值必须在 100 到 5000 之间")
                _post_json(self.base_url, f"/api/tasks/{task_id}/memory-policy", {"memory_compact_every_n_events": compact_every})
        except Exception as exc:
            if self.settings_error_label is not None:
                self.settings_error_label.setStringValue_(str(exc))
                self.settings_error_label.setTextColor_(NSColor.systemRedColor())
            return
        if self.settings_panel is not None:
            self.settings_panel.close()
        self.settings_panel = None
        self.settings_capturing_hotkey = None
        if self.settings_hotkey_capture_monitor is not None:
            NSEvent.removeMonitor_(self.settings_hotkey_capture_monitor)
            self.settings_hotkey_capture_monitor = None
        self._refresh_hotkey_registration()
        self.refreshStatus_(None)

    def switchTask_(self, sender):
        task_id = sender.representedObject()
        if not task_id:
            return
        try:
            _post_json(self.base_url, "/api/watch/switch-task", {"task_id": str(task_id)})
        finally:
            self.refreshStatus_(None)

    def openDataDir_(self, sender):
        try:
            payload = _request_json(self.base_url, "/api/control/open-data-dir")
        except Exception:
            return
        data_dir = str(payload.get("data_dir") or "").strip()
        if data_dir:
            subprocess.run(["open", data_dir], check=False)

    def quitApp_(self, sender):
        NSApp.terminate_(None)


def run_menu_bar(*, base_url: str = "http://127.0.0.1:8770") -> int:
    if NSApplication is None or NSStatusBar is None:
        raise RuntimeError("当前环境不支持 macOS 菜单栏控制")
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = _MenuBarController.alloc().initWithBaseURL_(base_url)
    app.setDelegate_(controller)
    app.run()
    return 0
