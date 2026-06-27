"""Build serializable structured observations from OCR and vision outputs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ayes.observation.entities import extract_entities_from_text
from ayes.vision.models import VisionResult


def build_structured_observation(
    *,
    region: Dict[str, Any],
    full_text: str,
    provider: str,
    blocks: List[Any],
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    block_payloads = [_normalize_block(block) for block in blocks]
    confidences = [float(block.get("confidence") or 0.0) for block in block_payloads]
    avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    primary_direction = ""
    for block in block_payloads:
        rect_norm = block.get("rect_norm") or {}
        primary_direction = _describe_direction(rect_norm)
        if primary_direction:
            break
    return {
        "observation_version": "1.0",
        "source": "ocr",
        "region": {
            "region_id": region.get("region_id") or "",
            "name": region.get("name") or "",
        },
        "text": {
            "full_text": full_text,
            "char_count": len((full_text or "").strip()),
            "provider": provider,
            "confidence": avg_confidence,
            "blocks": block_payloads,
        },
        "layout": {
            "primary_direction": primary_direction,
            "dense_text": len(block_payloads) >= 6,
            "block_count": len(block_payloads),
        },
        "visual": {
            "provider": "",
            "model": "",
            "summary": "",
            "detail_lines": [],
            "labels": [],
        },
        "entities": extract_entities_from_text(full_text),
        "warnings": list(warnings or []),
        "fusion_notes": [],
    }


def merge_vision_observation(
    observation: Dict[str, Any],
    *,
    result: VisionResult,
    fusion_notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    merged = {
        **observation,
        "source": "ocr+vision",
        "visual": {
            "provider": result.provider,
            "model": result.model,
            "summary": result.summary,
            "detail_lines": list((result.attributes or {}).get("detail_lines") or []),
            "labels": list(result.labels or []),
        },
        "fusion_notes": [*list(observation.get("fusion_notes") or []), *list(fusion_notes or [])],
    }
    return merged


def _normalize_block(block: Any) -> Dict[str, Any]:
    rect_norm = getattr(block, "rect_norm", None)
    rect = getattr(block, "rect", None)
    bbox = getattr(block, "bbox", None)
    if isinstance(block, dict):
        rect_norm = block.get("rect_norm") or rect_norm or {}
        rect = block.get("rect") or rect or {}
        bbox = block.get("bbox") or bbox or []
        text = block.get("text") or ""
        confidence = block.get("confidence") or 0.0
        line_index = block.get("line_index")
        block_type = block.get("block_type")
    else:
        text = getattr(block, "text", "") or ""
        confidence = getattr(block, "confidence", 0.0) or 0.0
        line_index = getattr(block, "line_index", None)
        block_type = getattr(block, "block_type", None)
    return {
        "text": text,
        "confidence": float(confidence),
        "bbox": list(bbox or []),
        "rect": rect or {},
        "rect_norm": rect_norm or {},
        "line_index": line_index,
        "block_type": block_type,
    }


def _describe_direction(rect_norm: Dict[str, Any]) -> str:
    if not rect_norm:
        return ""
    center_x = float(rect_norm.get("x", 0.0)) + (float(rect_norm.get("w", 0.0)) / 2.0)
    center_y = float(rect_norm.get("y", 0.0)) + (float(rect_norm.get("h", 0.0)) / 2.0)
    horizontal = "left"
    vertical = "top"
    if center_x >= 0.66:
        horizontal = "right"
    elif center_x >= 0.33:
        horizontal = "center"
    if center_y >= 0.66:
        vertical = "bottom"
    elif center_y >= 0.33:
        vertical = "middle"
    return f"{horizontal}_{vertical}"
