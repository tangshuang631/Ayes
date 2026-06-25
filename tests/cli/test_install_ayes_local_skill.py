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
    assert 'PYTHONPATH="$REPO_ROOT/src"' in content
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


def test_final_skill_source_dir_is_stateless_template() -> None:
    source_dir = Path("/Users/apple/Desktop/2026/Ayes/skills/final/ayes-local")
    files = sorted(path.relative_to(source_dir).as_posix() for path in source_dir.rglob("*") if path.is_file())

    assert "SKILL.md" in files
    assert "agents/openai.yaml" in files
    assert "references/installation.md" in files
    assert "references/commands.md" in files
    assert "references/troubleshooting.md" in files
    assert all(not item.startswith("runtime/") for item in files)
    assert all("/runtime/" not in item for item in files)
    assert all(not item.endswith(".db") for item in files)
