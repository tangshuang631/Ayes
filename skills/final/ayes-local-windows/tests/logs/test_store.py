from ayes.logs.store import LogStore


def test_log_store_filters_by_category() -> None:
    store = LogStore(retain_count=10)
    store.write(category="system", level="info", message="boot")
    store.write(category="watch", level="info", message="run")
    system_entries = store.list_entries(category="system")
    assert len(system_entries) == 1
    assert system_entries[0].message == "boot"


def test_log_store_suppresses_short_interval_duplicate_entries() -> None:
    written = []
    store = LogStore(retain_count=10, sink=lambda entry: written.append(entry))

    first = store.write(category="watch", level="info", message="run", task_id="task_a", timestamp=100.0)
    duplicate = store.write(category="watch", level="info", message="run", task_id="task_a", timestamp=101.0)
    later = store.write(category="watch", level="info", message="run", task_id="task_a", timestamp=131.0)

    assert duplicate is first
    assert later is not first
    entries = store.list_entries(category="watch", task_id="task_a")
    assert len(entries) == 2
    assert len(written) == 2
