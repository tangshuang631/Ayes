from pathlib import Path

from scripts import run_ayes_service


def test_run_ayes_service_ensure_project_src_on_path_inserts_src_dir(monkeypatch, tmp_path) -> None:
    root_dir = tmp_path / "Ayes"
    src_dir = root_dir / "src"
    src_dir.mkdir(parents=True)
    monkeypatch.setattr(run_ayes_service.sys, "path", ["existing"])

    run_ayes_service.ensure_project_src_on_path(root_dir)

    assert run_ayes_service.sys.path[0] == str(src_dir)
    assert "existing" in run_ayes_service.sys.path
