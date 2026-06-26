"""Local Ollama helper service for optional vision augmentation."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ayes.vision.models import VisionResult


class OllamaService:
    def __init__(self, command: str = "ollama") -> None:
        self.command = command

    def is_available(self) -> bool:
        return shutil.which(self.command) is not None

    def is_service_reachable(self) -> bool:
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return False

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
            models.append({"name": name, "id": model_id, "size": size, "modified": modified, "is_vision_model": self.is_vision_model_name(name)})
        return models

    def status_report(self, *, default_model: str = "qwen2.5vl:7b", selected_model: Optional[str] = None) -> Dict[str, Any]:
        binary_available = self.is_available()
        service_reachable = self.is_service_reachable() if binary_available else False
        items = self.list_models() if service_reachable else []
        installed_names = {str(item.get("name") or "") for item in items}
        default_model_installed = default_model in installed_names
        selected_model_installed = bool(selected_model and selected_model in installed_names)
        default_selected_model = ""
        if selected_model_installed:
            default_selected_model = str(selected_model)
        else:
            for item in items:
                if item.get("is_vision_model"):
                    default_selected_model = str(item.get("name") or "")
                    break
        available = binary_available and service_reachable
        if not binary_available:
            recommended_action = "install_ollama"
        elif not service_reachable:
            recommended_action = "start_service"
        elif not default_model_installed:
            recommended_action = "pull_default_model"
        else:
            recommended_action = "ready"
        return {
            "provider": "ollama",
            "available": available,
            "binary_available": binary_available,
            "service_reachable": service_reachable,
            "default_model": default_model,
            "default_model_installed": default_model_installed,
            "selected_model": selected_model or "",
            "selected_model_installed": selected_model_installed,
            "default_selected_model": default_selected_model,
            "items": items,
            "recommended_action": recommended_action,
        }

    @staticmethod
    def is_vision_model_name(name: str) -> bool:
        normalized = str(name or "").lower()
        markers = ["qwen2.5vl", "minicpm-v", "llava", "vision"]
        return "vl" in normalized or any(marker in normalized for marker in markers)

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
