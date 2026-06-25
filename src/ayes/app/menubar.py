"""macOS menu bar control surface for Ayes."""

from __future__ import annotations

import json
import webbrowser
import subprocess
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

try:
    from AppKit import (
        NSApp,
        NSApplication,
        NSApplicationActivationPolicyAccessory,
        NSMenu,
        NSMenuItem,
        NSStatusBar,
        NSObject,
    )
    from Foundation import NSTimer
except ImportError:  # pragma: no cover
    NSApp = None
    NSApplication = None
    NSApplicationActivationPolicyAccessory = None
    NSMenu = None
    NSMenuItem = None
    NSStatusBar = None
    NSObject = object
    NSTimer = None


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


def _safe_text(value: Any, fallback: str = "未设置") -> str:
    text = str(value or "").strip()
    return text or fallback


def _summarize_target(target: Any) -> str:
    if not isinstance(target, dict):
        return "目标：未设置"
    target_type = _safe_text(target.get("type"), "目标")
    if target_type == "process":
        name = _safe_text(target.get("process_name"), "未知进程")
        return f"目标：进程 {name}"
    if target_type == "window":
        title = _safe_text(target.get("window_title"), "未知窗口")
        return f"目标：窗口 {title}"
    if target_type == "screen":
        screen_id = _safe_text(target.get("screen_id"), "默认屏幕")
        return f"目标：屏幕 {screen_id}"
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
    )


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
    task_id = _safe_text(task.get("task_id"), "未知任务")
    mode = _safe_text(task.get("mode"), "")
    if mode:
        return f"{task_id} · {mode}"
    return task_id


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
        self.pause_item = None
        self.resume_item = None
        self.add_roi_item = None
        self.settings_item = None
        self.open_item = None
        self.quit_item = None
        return self

    def applicationDidFinishLaunching_(self, notification):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
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
        self.resume_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("恢复监控", "resumeAll:", "")
        self.add_roi_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("添加 / 管理 ROI...", "openRoiEditor:", "")
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
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.open_item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.settings_item)
        self.menu.addItem_(self.quit_item)
        self.status_item.setMenu_(self.menu)
        self.refreshStatus_(None)
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
            self.status_item.button().setTitle_("Ayes? ")
            return
        self.status_item.button().setTitle_(f"{summary.icon_glyph} {summary.title}")
        self.state_item.setTitle_(f"状态：{summary.state_line}")
        self.task_item.setTitle_(summary.task_line)
        self.target_item.setTitle_(summary.target_line)
        self.roi_item.setTitle_(summary.roi_line)
        self.recent_item.setTitle_(summary.recent_line)
        self.pause_item.setEnabled_(summary.has_runner and (not summary.is_paused))
        self.resume_item.setEnabled_(summary.has_runner and summary.is_paused)
        self.add_roi_item.setEnabled_(summary.has_runner)
        self.open_item.setEnabled_(True)
        self.settings_item.setEnabled_(True)
        self._set_recent_task_items(tasks)

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
        webbrowser.open(f"{self.base_url}/#roi-editor")

    def openSettings_(self, sender):
        webbrowser.open(f"{self.base_url}/#settings")

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
