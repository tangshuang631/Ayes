"""CLI helper functions."""

from __future__ import annotations

import json
from dataclasses import asdict

from ayes.config.models import WatchSpec


def load_watch_spec(path: str) -> WatchSpec:
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    return WatchSpec.from_dict(data)


def to_pretty_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
