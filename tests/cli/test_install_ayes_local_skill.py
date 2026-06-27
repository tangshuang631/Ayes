from pathlib import Path

from scripts import install_ayes_local_skill


def test_build_wrapper_script_binds_repo_root_and_python_bin() -> None:
    repo_root = Path("/Users/apple/Desktop/2026/Ayes")
    content = install_ayes_local_skill.build_wrapper_script(
        repo_root=repo_root,
        python_bin="python3",
        module="ayes.cli.agent_tool",
    )

    assert content.startswith("#!/bin/zsh")
    assert str(repo_root) in content
    assert 'if [ -d "$SKILL_DIR/src" ]; then' in content
    assert 'export PYTHONPATH="$SKILL_DIR/src"' in content
    assert 'export PYTHONPATH="$REPO_ROOT/src"' in content
    assert 'SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"' in content
    assert 'export AYES_RUNTIME_DIR="$SKILL_DIR/runtime"' in content
    assert "-m ayes.cli.agent_tool" in content


def test_build_install_paths_targets_skill_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "Ayes"
    repo_root.mkdir()
    skill_root = tmp_path / ".codex" / "skills"
    paths = install_ayes_local_skill.build_install_paths(repo_root=repo_root, skill_root=skill_root)

    assert paths.source_skill_dir == repo_root / "skills" / "final" / "ayes-local"
    assert paths.target_skill_dir == skill_root / "ayes-local"
    assert paths.target_scripts_dir == skill_root / "ayes-local" / "scripts"
    assert paths.agent_wrapper_path == skill_root / "ayes-local" / "scripts" / "ayes-agent-local"
    assert paths.menubar_wrapper_path == skill_root / "ayes-local" / "scripts" / "ayes-menubar-local"


def test_install_skill_preserves_existing_runtime_directory(tmp_path: Path) -> None:
    repo_root = tmp_path / "Ayes"
    source_dir = repo_root / "skills" / "final" / "ayes-local"
    (source_dir / "references").mkdir(parents=True)
    (source_dir / "SKILL.md").write_text("skill", encoding="utf-8")
    (source_dir / "references" / "commands.md").write_text("commands", encoding="utf-8")
    skill_root = tmp_path / ".codex" / "skills"
    installed_runtime = skill_root / "ayes-local" / "runtime"
    installed_runtime.mkdir(parents=True)
    (installed_runtime / "state.db").write_text("keep", encoding="utf-8")

    paths = install_ayes_local_skill.install_skill(repo_root=repo_root, skill_root=skill_root)

    assert (paths.target_skill_dir / "runtime" / "state.db").read_text(encoding="utf-8") == "keep"
    assert (paths.target_skill_dir / "SKILL.md").read_text(encoding="utf-8") == "skill"


def test_build_install_paths_accepts_standalone_release_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "ayes-local"
    (repo_root / "SKILL.md").parent.mkdir(parents=True)
    (repo_root / "SKILL.md").write_text("skill", encoding="utf-8")
    (repo_root / "src" / "ayes").mkdir(parents=True)
    skill_root = tmp_path / ".codex" / "skills"

    paths = install_ayes_local_skill.build_install_paths(repo_root=repo_root, skill_root=skill_root)

    assert paths.source_skill_dir == repo_root


def test_final_skill_source_dir_is_stateless_template() -> None:
    source_dir = Path("/Users/apple/Desktop/2026/Ayes/skills/final/ayes-local")
    files = sorted(path.relative_to(source_dir).as_posix() for path in source_dir.rglob("*") if path.is_file())

    assert "SKILL.md" in files
    assert "agents/openai.yaml" in files
    assert "references/installation.md" in files
    assert "references/commands.md" in files
    assert "references/troubleshooting.md" in files
    assert "references/privacy.md" in files
    assert "references/uninstall.md" in files
    assert "references/release-checklist.md" in files
    assert "references/menubar-manual-test.md" in files
    assert "references/stress-test.md" in files
    assert "scripts/install_ayes_local_skill.py" in files
    assert "scripts/run_ayes_service.py" in files
    assert "src/ayes/cli/agent_tool.py" in files
    assert "README.md" in files
    assert "requirements.txt" in files
    assert all(not item.startswith("runtime/") for item in files)
    assert all("/runtime/" not in item for item in files)
    assert all(not item.endswith(".db") for item in files)


def test_windows_final_skill_source_dir_is_stateless_template() -> None:
    source_dir = Path("/Users/apple/Desktop/2026/Ayes/skills/final/ayes-local-windows")
    files = sorted(path.relative_to(source_dir).as_posix() for path in source_dir.rglob("*") if path.is_file())

    assert "SKILL.md" in files
    assert "README.md" in files
    assert "requirements.txt" in files
    assert "references/windows.md" in files
    assert "references/commands.md" in files
    assert "references/privacy.md" in files
    assert "scripts/install_ayes_local_skill.py" in files
    assert "scripts/run_ayes_service.py" in files
    assert "scripts/ayes-agent-local.ps1" in files
    assert "scripts/ayes-tray-local.ps1" in files
    assert "src/ayes/cli/windows_tray.py" in files
    assert "src/ayes/cli/agent_tool.py" in files
    assert all(not item.startswith("runtime/") for item in files)
    assert all("/runtime/" not in item for item in files)
    assert all(not item.endswith(".db") for item in files)


def test_root_readme_routes_users_to_mac_or_windows_skill() -> None:
    readme = Path("/Users/apple/Desktop/2026/Ayes/README.md").read_text(encoding="utf-8")

    assert "skills/final/ayes-local/" in readme
    assert "skills/final/ayes-local-windows/" in readme
    assert "Windows" in readme
    assert "macOS" in readme


def test_windows_powershell_wrappers_use_installed_skill_runtime() -> None:
    source_dir = Path("/Users/apple/Desktop/2026/Ayes/skills/final/ayes-local-windows")
    agent_wrapper = (source_dir / "scripts" / "ayes-agent-local.ps1").read_text(encoding="utf-8")
    tray_wrapper = (source_dir / "scripts" / "ayes-tray-local.ps1").read_text(encoding="utf-8")

    assert "$env:PYTHONPATH = $SrcDir" in agent_wrapper
    assert "$env:AYES_RUNTIME_DIR = Join-Path $SkillDir 'runtime'" in agent_wrapper
    assert "python -m ayes.cli.agent_tool @args" in agent_wrapper
    assert "python -m ayes.cli.windows_tray @args" in tray_wrapper
