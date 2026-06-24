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
    assert "-m ayes.cli.agent_tool" in content


def test_build_install_paths_targets_skill_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "Ayes"
    repo_root.mkdir()
    skill_root = tmp_path / ".codex" / "skills"
    paths = install_ayes_local_skill.build_install_paths(repo_root=repo_root, skill_root=skill_root)

    assert paths.source_skill_dir == repo_root / "skills" / "ayes-local"
    assert paths.target_skill_dir == skill_root / "ayes-local"
    assert paths.target_scripts_dir == skill_root / "ayes-local" / "scripts"
