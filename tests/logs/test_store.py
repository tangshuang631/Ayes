from ayes.logs.store import LogStore


def test_log_store_filters_by_category() -> None:
    store = LogStore(retain_count=10)
    store.write(category="system", level="info", message="boot")
    store.write(category="watch", level="info", message="run")
    system_entries = store.list_entries(category="system")
    assert len(system_entries) == 1
    assert system_entries[0].message == "boot"
