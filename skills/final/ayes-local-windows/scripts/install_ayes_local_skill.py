#!/usr/bin/env python3
"""Install the Windows ayes-local skill into a target skill root."""

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
    tray_wrapper_path: Path


def build_install_paths(*, repo_root: Path, skill_root: Path) -> InstallPaths:
    resolved_repo_root = repo_root.resolve()
    resolved_skill_root = skill_root.resolve()
    bundled_skill_dir = resolved_repo_root / "skills" / "final" / "ayes-local-windows"
    standalone_skill_dir = resolved_repo_root
    source_skill_dir = bundled_skill_dir if bundled_skill_dir.exists() else (standalone_skill_dir if (standalone_skill_dir / "SKILL.md").exists() else bundled_skill_dir)
    target_skill_dir = resolved_skill_root / "ayes-local"
    target_scripts_dir = target_skill_dir / "scripts"
    return InstallPaths(
        repo_root=resolved_repo_root,
        skill_root=resolved_skill_root,
        source_skill_dir=source_skill_dir,
        target_skill_dir=target_skill_dir,
        target_scripts_dir=target_scripts_dir,
        agent_wrapper_path=target_scripts_dir / "ayes-agent-local.ps1",
        tray_wrapper_path=target_scripts_dir / "ayes-tray-local.ps1",
    )


def build_powershell_wrapper(*, python_bin: str, module: str) -> str:
    python_literal = python_bin.replace("'", "''")
    module_literal = module.replace("'", "''")
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "$SkillDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)\n"
        "$SrcDir = Join-Path $SkillDir 'src'\n"
        "$env:PYTHONPATH = $SrcDir\n"
        "$env:AYES_RUNTIME_DIR = Join-Path $SkillDir 'runtime'\n"
        f"& '{python_literal}' -m '{module_literal}' @args\n"
        "exit $LASTEXITCODE\n"
    )


def install_skill(*, repo_root: Path, skill_root: Path, python_bin: str = "python") -> InstallPaths:
    paths = build_install_paths(repo_root=repo_root, skill_root=skill_root)
    if not paths.source_skill_dir.exists():
        raise FileNotFoundError(f"未找到 Windows skill 模板目录: {paths.source_skill_dir}")
    paths.skill_root.mkdir(parents=True, exist_ok=True)
    runtime_backup = None
    if paths.target_skill_dir.exists():
        runtime_dir = paths.target_skill_dir / "runtime"
        if runtime_dir.exists():
            runtime_backup = paths.skill_root / ".ayes-local-runtime-backup"
            if runtime_backup.exists():
                shutil.rmtree(runtime_backup)
            shutil.move(str(runtime_dir), str(runtime_backup))
        shutil.rmtree(paths.target_skill_dir)
    shutil.copytree(paths.source_skill_dir, paths.target_skill_dir)
    if runtime_backup is not None and runtime_backup.exists():
        shutil.move(str(runtime_backup), str(paths.target_skill_dir / "runtime"))
    paths.target_scripts_dir.mkdir(parents=True, exist_ok=True)
    paths.agent_wrapper_path.write_text(build_powershell_wrapper(python_bin=python_bin, module="ayes.cli.agent_tool"), encoding="utf-8")
    paths.tray_wrapper_path.write_text(build_powershell_wrapper(python_bin=python_bin, module="ayes.cli.windows_tray"), encoding="utf-8")
    return paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="安装 Windows ayes-local skill 到本地智能体 skill 目录")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--skill-root", default=str(Path.home() / ".codex" / "skills"))
    parser.add_argument("--python-bin", default="python")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = install_skill(repo_root=Path(args.repo_root), skill_root=Path(args.skill_root), python_bin=args.python_bin)
    print(f"已安装 Windows ayes-local skill: {paths.target_skill_dir}")
    print(f"本地 agent 包装命令: {paths.agent_wrapper_path}")
    print(f"本地 tray 包装命令: {paths.tray_wrapper_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
