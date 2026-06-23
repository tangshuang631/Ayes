"""API-level task and timeline helpers for agent-style access."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Dict, Optional

from ayes.config.models import WatchSpec


def build_task_payload(*, task_id: str, spec: WatchSpec) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "mode": spec.mode,
        "target": asdict(spec.target),
        "spec": asdict(spec),
        "created_at": time.time(),
    }
