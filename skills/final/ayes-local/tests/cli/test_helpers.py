from ayes.cli.helpers import to_pretty_json


def test_to_pretty_json_preserves_utf8_text() -> None:
    payload = {"answer": "库存恢复"}
    rendered = to_pretty_json(payload)
    assert "库存恢复" in rendered
