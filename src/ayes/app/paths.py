"""Runtime path helpers shared by service, API, and local skill wrappers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def runtime_root(root_dir: Optional[Path] = None) -> Path:
    configured = os.environ.get("AYES_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return ((root_dir or repo_root()).resolve() / "runtime").resolve()
