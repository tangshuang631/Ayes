import json
from pathlib import Path

from ayes.cli.spec_builder import build_window_observe_spec


def test_build_window_observe_spec_writes_window_target(tmp_path: Path) -> None:
    output = tmp_path / "window.json"
    build_window_observe_spec(window_id=42, output_path=str(output))
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["target"]["type"] == "window"
    assert payload["target"]["window_id"] == 42
    assert payload["memory"]["short_term"]["retain_days"] == 7
    assert payload["memory"]["long_term"]["retain_days"] == 14
    assert payload["memory"]["disable_auto_cleanup"] is False
