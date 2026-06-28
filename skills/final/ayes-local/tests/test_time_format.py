from ayes.api import contracts
from ayes.memory.short_term import format_human_time


def test_contract_time_text_uses_local_timezone() -> None:
    assert contracts._format_time_text(0) == "08:00:00"


def test_short_term_human_time_uses_local_timezone() -> None:
    assert format_human_time(0) == "08:00:00"
