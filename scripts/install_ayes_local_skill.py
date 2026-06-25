#!/usr/bin/env python3
"""Install the ayes-local skill into a target skill root."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstallPaths:
    repo_root: Path
    skill_root: Path
    source_skill_dir: Path
    target_skill_dir: Path
    target_scripts_dir: Path
    agent_wrapper_path: Path
    menubar_wrapper_path: Path


def build_install_paths(*, repo_root: Path, skill_root: Path) -> InstallPaths:
    resolved_repo_root = repo_root.resolve()
    resolved_skill_root = skill_root.resolve()
    target_skill_dir = resolved_skill_root / "ayes-local"
    target_scripts_dir = target_skill_dir / "scripts"
    return InstallPaths(
        repo_root=resolved_repo_root,
        skill_root=resolved_skill_root,
        source_skill_dir=resolved_repo_root / "skills" / "final" / "ayes-local",
        target_skill_dir=target_skill_dir,
        target_scripts_dir=target_scripts_dir,
        agent_wrapper_path=target_scripts_dir / "ayes-agent-local",
        menubar_wrapper_path=target_scripts_dir / "ayes-menubar-local",
    )


def build_wrapper_script(*, repo_root: Path, python_bin: str, module: str) -> str:
    repo_root_posix = repo_root.resolve().as_posix().replace('"', '\\"')
    return (
        "#!/bin/zsh\n"
        "set -euo pipefail\n"
        'SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"\n'
        f'REPO_ROOT="{repo_root_posix}"\n'
        f'PYTHON_BIN="{python_bin}"\n'
        'export PYTHONPATH="$REPO_ROOT/src"\n'
        'export AYES_RUNTIME_DIR="$SKILL_DIR/runtime"\n'
        'exec "$PYTHON_BIN" -m ' + module + ' "$@"\n'
    )


def install_skill(
    *,
    repo_root: Path,
    skill_root: Path,
    python_bin: str = "python3",
    module: str = "ayes.cli.agent_tool",
    menubar_module: str = "ayes.cli.menubar",
) -> InstallPaths:
    paths = build_install_paths(repo_root=repo_root, skill_root=skill_root)
    if not paths.source_skill_dir.exists():
        raise FileNotFoundError(f"未找到 skill 模板目录: {paths.source_skill_dir}")
    paths.skill_root.mkdir(parents=True, exist_ok=True)
    if paths.target_skill_dir.exists():
        shutil.rmtree(paths.target_skill_dir)
    shutil.copytree(paths.source_skill_dir, paths.target_skill_dir)
    paths.target_scripts_dir.mkdir(parents=True, exist_ok=True)
    agent_wrapper = build_wrapper_script(repo_root=paths.repo_root, python_bin=python_bin, module=module)
    menubar_wrapper = build_wrapper_script(repo_root=paths.repo_root, python_bin=python_bin, module=menubar_module)
    paths.agent_wrapper_path.write_text(agent_wrapper, encoding="utf-8")
    paths.agent_wrapper_path.chmod(0o755)
    paths.menubar_wrapper_path.write_text(menubar_wrapper, encoding="utf-8")
    paths.menubar_wrapper_path.chmod(0o755)
    return paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="安装 ayes-local skill 到本地智能体 skill 目录")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--skill-root", default=str(Path.home() / ".codex" / "skills"))
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument("--module", default="ayes.cli.agent_tool")
    parser.add_argument("--menubar-module", default="ayes.cli.menubar")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = install_skill(
        repo_root=Path(args.repo_root),
        skill_root=Path(args.skill_root),
        python_bin=args.python_bin,
        module=args.module,
        menubar_module=args.menubar_module,
    )
    print(f"已安装 ayes-local skill: {paths.target_skill_dir}")
    print(f"本地 agent 包装命令: {paths.agent_wrapper_path}")
    print(f"本地 menubar 包装命令: {paths.menubar_wrapper_path}")
    print("安装后建议验证：")
    print(f"  {paths.agent_wrapper_path} ensure-service")
    print(f"  {paths.agent_wrapper_path} contracts")
    print(f"  {paths.agent_wrapper_path} status")
    print(f"  {paths.menubar_wrapper_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
