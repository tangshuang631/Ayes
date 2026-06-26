"""Entity extraction helpers for structured observations."""

from __future__ import annotations

import re
from typing import Dict, List


def extract_entities_from_text(text: str) -> List[Dict[str, object]]:
    normalized = str(text or "").replace(",", "").replace("，", "")
    entities: List[Dict[str, object]] = []

    for match in re.finditer(r"(?:价格|售价|现价|到手价)\s*[:：=]?\s*[¥￥$]?\s*(-?\d+(?:\.\d+)?)", normalized, flags=re.IGNORECASE):
        value = float(match.group(1))
        entities.append(
            {
                "type": "numeric",
                "field": "price",
                "value": value,
                "unit": "CNY",
                "evidence": match.group(0),
            }
        )

    for match in re.finditer(r"(?:库存|余量|剩余)\s*[:：=]?\s*(-?\d+(?:\.\d+)?)", normalized, flags=re.IGNORECASE):
        value = float(match.group(1))
        entities.append(
            {
                "type": "numeric",
                "field": "stock",
                "value": value,
                "unit": "count",
                "evidence": match.group(0),
            }
        )

    if not any(entity["field"] == "price" for entity in entities):
        for match in re.finditer(r"[¥￥$]\s*(-?\d+(?:\.\d+)?)", normalized):
            value = float(match.group(1))
            entities.append(
                {
                    "type": "numeric",
                    "field": "price",
                    "value": value,
                    "unit": "CNY",
                    "evidence": match.group(0),
                }
            )

    unique: List[Dict[str, object]] = []
    seen = set()
    for entity in entities:
        key = (entity["field"], entity["value"], entity["evidence"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(entity)
    return unique
