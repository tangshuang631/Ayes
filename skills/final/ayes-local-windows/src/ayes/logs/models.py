"""Log entry structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class LogEntry:
    log_id: str
    timestamp: float
    category: str
    level: str
    message: str
    task_id: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)
