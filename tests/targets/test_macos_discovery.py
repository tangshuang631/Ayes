from ayes.targets.discovery.macos import MacOSWindowDiscovery


def test_convert_raw_windows_filters_invalid_entries_and_sorts_business_first() -> None:
    discovery = MacOSWindowDiscovery()
    candidates = discovery._convert_raw_windows(
        [
            {
                "kCGWindowNumber": 1,
                "kCGWindowOwnerPID": 100,
                "kCGWindowOwnerName": "HelperApp",
                "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 80, "Height": 80},
                "kCGWindowLayer": 1,
                "kCGWindowIsOnscreen": False,
                "kCGWindowAlpha": 1,
            },
            {
                "kCGWindowNumber": 2,
                "kCGWindowOwnerPID": 101,
                "kCGWindowOwnerName": "MainApp",
                "kCGWindowName": "商品页",
                "kCGWindowBounds": {"X": 10, "Y": 10, "Width": 1200, "Height": 800},
                "kCGWindowLayer": 0,
                "kCGWindowIsOnscreen": True,
                "kCGWindowAlpha": 1,
            },
            {
                "kCGWindowNumber": 3,
                "kCGWindowOwnerPID": 102,
                "kCGWindowOwnerName": "",
                "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 400, "Height": 300},
                "kCGWindowLayer": 0,
                "kCGWindowIsOnscreen": True,
                "kCGWindowAlpha": 1,
            },
        ]
    )
    assert len(candidates) == 2
    assert candidates[0].process_name == "MainApp"
    assert candidates[0].is_business_candidate is True
    assert candidates[1].observability.code == "partial"


def test_missing_quartz_is_supported_as_empty_result() -> None:
    discovery = MacOSWindowDiscovery()
    discovery.is_available = False
    assert discovery.list_windows() == []
