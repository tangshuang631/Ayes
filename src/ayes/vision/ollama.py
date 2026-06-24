"""Local Ollama helper service for optional vision augmentation."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import urllib.request
from typing import Any, Dict, List

from ayes.vision.models import VisionResult


class OllamaService:
    def __init__(self, command: str = "ollama") -> None:
        self.command = command

    def is_available(self) -> bool:
        return shutil.which(self.command) is not None

    def list_models(self) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        result = subprocess.run(
            [self.command, "list"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        raw = result.stdout.strip()
        if not raw:
            return []
        models: List[Dict[str, Any]] = []
        lines = raw.splitlines()
        if lines and "NAME" in lines[0]:
            lines = lines[1:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if not parts:
                continue
            name = parts[0]
            model_id = parts[1] if len(parts) > 1 else ""
            size = parts[2] if len(parts) > 2 else ""
            modified = " ".join(parts[3:]) if len(parts) > 3 else ""
            models.append({"name": name, "id": model_id, "size": size, "modified": modified})
        return models

    def generate_vision_summary(
        self,
        *,
        model: str,
        image_bytes: bytes,
        prompt: str,
    ) -> VisionResult:
        if not self.is_available():
            raise RuntimeError("Ollama 当前不可用")
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [base64.b64encode(image_bytes).decode("utf-8")],
            "stream": False,
        }
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            raw = urllib.request.urlopen(request, timeout=60).read().decode("utf-8")
        except Exception as exc:
            raise RuntimeError(f"Ollama 视觉调用失败: {exc}") from exc
        response = json.loads(raw)
        text = str(response.get("response") or "").strip()
        lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
        summary = lines[0].strip() if lines else ""
        detail_lines = lines[1:6] if len(lines) > 1 else []
        return VisionResult(
            provider="ollama",
            model=model,
            summary=summary,
            labels=[],
            attributes={
                "raw_text": text,
                "detail_lines": detail_lines,
                "detail_count": len(detail_lines),
                "request_payload": payload,
            },
        )
