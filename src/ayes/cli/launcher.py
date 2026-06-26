"""Launcher commands for the local Ayes background service."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import shutil
import os
import subprocess
import sys
from pathlib import Path

from ayes.app.service_control import default_service_config, ensure_service_started, start_idle_monitor


@dataclass(frozen=True)
class LauncherPaths:
    runtime_app_path: Path
    desktop_app_path: Path
    start_script_path: Path


def build_launcher_paths(root_dir: Path, *, desktop_dir: Path | None = None) -> LauncherPaths:
    resolved_root = root_dir.resolve()
    target_desktop = (desktop_dir or Path.home() / "Desktop").resolve()
    return LauncherPaths(
        runtime_app_path=resolved_root / "runtime" / "Ayes 启动器.app",
        desktop_app_path=target_desktop / "Ayes 启动器.app",
        start_script_path=resolved_root / "scripts" / "start_ayes_service.sh",
    )


def build_launcher_executable_script(start_script_path: Path) -> str:
    posix_path = start_script_path.as_posix().replace('"', '\\"')
    return (
        "#!/bin/zsh\n"
        "set -euo pipefail\n"
        f'START_SCRIPT="{posix_path}"\n'
        'nohup /bin/zsh "$START_SCRIPT" >/dev/null 2>&1 &\n'
        "exit 0\n"
    )


def build_launcher_info_plist() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>Ayes 启动器</string>
  <key>CFBundleExecutable</key>
  <string>AyesLauncher</string>
  <key>CFBundleIdentifier</key>
  <string>com.ayes.launcher</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Ayes 启动器</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSBackgroundOnly</key>
  <false/>
</dict>
</plist>
"""


def _open_browser(url: str) -> None:
    subprocess.run(["open", url], check=False)


def cmd_start() -> int:
    config = default_service_config(Path(__file__).resolve().parents[3])
    result = ensure_service_started(config)
    start_idle_monitor(config, idle_timeout_sec=max(int(os.environ.get("AYES_IDLE_TIMEOUT_SEC", "120")), 1))
    _open_browser(config.base_url)
    print(result)
    return 0


def cmd_build_app(*, install_to_desktop: bool) -> int:
    root_dir = Path(__file__).resolve().parents[3]
    paths = build_launcher_paths(root_dir)
    contents_dir = paths.runtime_app_path / "Contents"
    macos_dir = contents_dir / "MacOS"
    contents_dir.mkdir(parents=True, exist_ok=True)
    macos_dir.mkdir(parents=True, exist_ok=True)
    (contents_dir / "Info.plist").write_text(build_launcher_info_plist(), encoding="utf-8")
    executable_path = macos_dir / "AyesLauncher"
    executable_path.write_text(build_launcher_executable_script(paths.start_script_path), encoding="utf-8")
    executable_path.chmod(0o755)
    if install_to_desktop:
        subprocess.run(["rm", "-rf", str(paths.desktop_app_path)], check=True)
        shutil.copytree(paths.runtime_app_path, paths.desktop_app_path)
        print(paths.desktop_app_path)
        return 0
    print(paths.runtime_app_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ayes launcher helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start", help="确保后台服务为单实例并打开前端页面")
    build_app_parser = subparsers.add_parser("build-app", help="构建桌面启动器 App")
    build_app_parser.add_argument("--install-to-desktop", action="store_true", help="同时安装到桌面")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "start":
        return cmd_start()
    if args.command == "build-app":
        return cmd_build_app(install_to_desktop=bool(args.install_to_desktop))
    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
