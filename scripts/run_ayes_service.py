#!/usr/bin/env python3
"""Start Ayes uvicorn service as a detached background process."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def ensure_project_src_on_path(root_dir: Path | None = None) -> Path:
    resolved_root = (root_dir or Path(__file__).resolve().parents[1]).resolve()
    src_dir = resolved_root / "src"
    src_text = str(src_dir)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
    return src_dir


ensure_project_src_on_path()

from ayes.app.service_control import default_service_config


def main() -> int:
    config = default_service_config(Path(__file__).resolve().parents[1])
    config.runtime_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    src_path = str(config.root_dir / "src")
    env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"

    with config.log_file.open("ab") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "ayes.api.server:app",
                "--host",
                config.host,
                "--port",
                str(config.port),
            ],
            cwd=str(config.root_dir),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    config.pid_file.write_text(str(process.pid), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
