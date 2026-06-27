from pathlib import Path

from ayes.cli.launcher import build_launcher_executable_script, build_launcher_info_plist, build_launcher_paths


def test_build_launcher_executable_script_points_to_start_script() -> None:
    script_path = Path("/Users/apple/Desktop/2026/Ayes/scripts/start_ayes_service.sh")
    content = build_launcher_executable_script(script_path)
    assert content.startswith("#!/bin/zsh")
    assert str(script_path) in content
    assert ">/dev/null 2>&1 &" in content
    assert "exec" not in content


def test_build_launcher_info_plist_contains_bundle_metadata() -> None:
    content = build_launcher_info_plist()
    assert "CFBundleDisplayName" in content
    assert "Ayes 启动器" in content
    assert "CFBundleExecutable" in content
    assert "AyesLauncher" in content


def test_build_launcher_paths_include_runtime_app_and_desktop_install_target(tmp_path: Path) -> None:
    paths = build_launcher_paths(tmp_path, desktop_dir=Path("/Users/apple/Desktop"))
    assert paths.runtime_app_path == tmp_path / "runtime" / "Ayes 启动器.app"
    assert paths.desktop_app_path == Path("/Users/apple/Desktop") / "Ayes 启动器.app"
