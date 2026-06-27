"""Windows tray control surface for Ayes."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8770"


def _request_json(base_url: str, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _skill_dir() -> Path:
    return Path(__file__).resolve().parents[3]


def _run_agent_command(*args: str) -> None:
    subprocess.Popen([sys.executable, "-m", "ayes.cli.agent_tool", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _open_path(path: str) -> None:
    if path:
        subprocess.Popen(["explorer", path])


class WindowsTrayApp:
    def __init__(self, *, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.icon = None

    def status_text(self) -> str:
        try:
            status = _request_json(self.base_url, "/api/control/status")
        except Exception:
            return "Ayes 未连接"
        if status.get("is_paused"):
            return "Ayes 已暂停"
        if status.get("is_running"):
            return "Ayes 监控中"
        if status.get("has_runner"):
            return "Ayes 已装载"
        return "Ayes 未运行"

    def ensure_service(self) -> None:
        _run_agent_command("ensure-service")

    def start(self) -> None:
        _run_agent_command("start")

    def pause(self) -> None:
        self._post("/api/control/pause-all")

    def resume(self) -> None:
        self._post("/api/control/resume-all")

    def open_data_dir(self) -> None:
        try:
            payload = _request_json(self.base_url, "/api/control/open-data-dir")
            _open_path(str(payload.get("path") or payload.get("runtime_dir") or _skill_dir() / "runtime"))
        except Exception:
            _open_path(str(_skill_dir() / "runtime"))

    def open_settings(self) -> None:
        try:
            _show_settings_dialog(self.base_url)
        except Exception as exc:
            _show_error(f"Ayes 设置打开失败: {exc}")

    def quit(self) -> None:
        if self.icon is not None:
            self.icon.stop()

    def _post(self, path: str) -> None:
        try:
            _request_json(self.base_url, path, method="POST", payload={})
        except Exception:
            pass

    def build_menu(self):
        import pystray  # type: ignore

        return pystray.Menu(
            pystray.MenuItem(lambda item: self.status_text(), None, enabled=False),
            pystray.MenuItem("确保服务启动", lambda icon, item: self.ensure_service()),
            pystray.MenuItem("开始 / 继续当前任务", lambda icon, item: self.start()),
            pystray.MenuItem("暂停监控", lambda icon, item: self.pause()),
            pystray.MenuItem("继续上次的监控", lambda icon, item: self.resume()),
            pystray.MenuItem("设置...", lambda icon, item: self.open_settings()),
            pystray.MenuItem("打开数据目录", lambda icon, item: self.open_data_dir()),
            pystray.MenuItem("退出控制面", lambda icon, item: self.quit()),
        )

    def run(self) -> int:
        try:
            import pystray  # type: ignore
            from PIL import Image, ImageDraw  # type: ignore
        except ImportError as exc:
            print(f"Windows 托盘依赖缺失: {exc}. 请先 pip install -r requirements.txt", file=sys.stderr)
            return 2

        image = Image.new("RGB", (64, 64), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((12, 12, 52, 52), outline=(20, 20, 20), width=5)
        draw.ellipse((26, 26, 38, 38), fill=(20, 20, 20))
        self.icon = pystray.Icon("Ayes", image, "Ayes", self.build_menu())
        threading.Thread(target=self.ensure_service, daemon=True).start()
        self.icon.run()
        return 0


def _show_settings_dialog(base_url: str) -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    try:
        settings = (_request_json(base_url, "/api/control/settings").get("settings") or {})
        sampling = (_request_json(base_url, "/api/control/sampling").get("sampling") or {})
    except Exception as exc:
        raise RuntimeError(f"无法连接本地 Ayes 服务: {exc}") from exc

    root = tk.Tk()
    root.title("Ayes 设置")
    root.geometry("420x330")
    root.resizable(False, False)

    interval = tk.StringVar(value=str((int(sampling.get("interval_ms") or 6000)) / 1000))
    quality = tk.StringVar(value=str(sampling.get("quality") or "standard"))
    save_screenshots = tk.BooleanVar(value=bool(sampling.get("save_ocr_screenshots", False)))
    latest_hotkey = tk.StringVar(value=str(settings.get("latest_frame_hotkey") or ""))
    context_hotkey = tk.StringVar(value=str(settings.get("monitor_context_hotkey") or ""))

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Ayes Windows 设置", font=("", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
    ttk.Label(frame, text="采样间隔（秒）").grid(row=1, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=interval, width=18).grid(row=1, column=1, sticky="w")
    ttk.Label(frame, text="采样质量").grid(row=2, column=0, sticky="w", pady=6)
    ttk.Combobox(frame, textvariable=quality, values=["original", "standard", "space_saver", "ultra_saver"], state="readonly", width=16).grid(row=2, column=1, sticky="w")
    ttk.Checkbutton(frame, text="保存事件证据截图", variable=save_screenshots).grid(row=3, column=0, columnspan=2, sticky="w", pady=8)
    ttk.Label(frame, text="截图快捷键").grid(row=4, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=latest_hotkey, width=22).grid(row=4, column=1, sticky="w")
    ttk.Label(frame, text="提问快捷键").grid(row=5, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=context_hotkey, width=22).grid(row=5, column=1, sticky="w")
    ttk.Label(frame, text="提问快捷键粘贴: Ayes context mode").grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 12))

    def save() -> None:
        try:
            interval_ms = int(float(interval.get()) * 1000)
            _request_json(
                base_url,
                "/api/control/sampling",
                method="POST",
                payload={"interval_ms": interval_ms, "quality": quality.get(), "save_ocr_screenshots": save_screenshots.get()},
            )
            result = _request_json(
                base_url,
                "/api/control/settings",
                method="POST",
                payload={"latest_frame_hotkey": latest_hotkey.get(), "monitor_context_hotkey": context_hotkey.get()},
            )
            if result.get("error"):
                raise RuntimeError(str(result["error"]))
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        root.destroy()

    ttk.Button(frame, text="保存", command=save).grid(row=7, column=1, sticky="e", pady=14)
    ttk.Button(frame, text="取消", command=root.destroy).grid(row=7, column=0, sticky="w", pady=14)
    root.mainloop()


def _show_error(message: str) -> None:
    try:
        import tkinter.messagebox as messagebox

        messagebox.showerror("Ayes", message)
    except Exception:
        print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    app = WindowsTrayApp()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
