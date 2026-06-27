from ayes.targets.discovery import create_window_discovery
from ayes.targets.discovery.macos import MacOSWindowDiscovery
from ayes.targets.discovery.windows import WindowsWindowDiscovery


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


def test_windows_discovery_is_supported_as_empty_result_when_backend_unavailable() -> None:
    discovery = WindowsWindowDiscovery()
    discovery.is_available = False

    assert discovery.list_windows() == []


def test_create_window_discovery_returns_platform_backend() -> None:
    assert create_window_discovery(platform_name="darwin").__class__.__name__ == "MacOSWindowDiscovery"
    assert create_window_discovery(platform_name="win32").__class__.__name__ == "WindowsWindowDiscovery"


def test_get_primary_window_for_process_prefers_observable_business_window() -> None:
    discovery = MacOSWindowDiscovery()
    discovery.is_available = False
    discovery.list_windows = lambda: discovery._convert_raw_windows(
        [
            {
                "kCGWindowNumber": 1,
                "kCGWindowOwnerPID": 100,
                "kCGWindowOwnerName": "TargetApp",
                "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 420, "Height": 320},
                "kCGWindowLayer": 2,
                "kCGWindowIsOnscreen": False,
                "kCGWindowAlpha": 1,
            },
            {
                "kCGWindowNumber": 2,
                "kCGWindowOwnerPID": 100,
                "kCGWindowOwnerName": "TargetApp",
                "kCGWindowName": "商品详情",
                "kCGWindowBounds": {"X": 10, "Y": 10, "Width": 1280, "Height": 820},
                "kCGWindowLayer": 0,
                "kCGWindowIsOnscreen": True,
                "kCGWindowAlpha": 1,
            },
            {
                "kCGWindowNumber": 3,
                "kCGWindowOwnerPID": 101,
                "kCGWindowOwnerName": "OtherApp",
                "kCGWindowName": "无关窗口",
                "kCGWindowBounds": {"X": 20, "Y": 20, "Width": 1600, "Height": 900},
                "kCGWindowLayer": 0,
                "kCGWindowIsOnscreen": True,
                "kCGWindowAlpha": 1,
            },
        ]
    )

    candidate = discovery.get_primary_window_for_process(process_name="TargetApp")

    assert candidate is not None
    assert candidate.window_id == 2


def test_get_primary_window_for_process_can_match_process_id() -> None:
    discovery = MacOSWindowDiscovery()
    discovery.is_available = False
    discovery.list_windows = lambda: discovery._convert_raw_windows(
        [
            {
                "kCGWindowNumber": 11,
                "kCGWindowOwnerPID": 200,
                "kCGWindowOwnerName": "TargetApp",
                "kCGWindowName": "库存面板",
                "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 960, "Height": 720},
                "kCGWindowLayer": 0,
                "kCGWindowIsOnscreen": True,
                "kCGWindowAlpha": 1,
            },
            {
                "kCGWindowNumber": 12,
                "kCGWindowOwnerPID": 201,
                "kCGWindowOwnerName": "TargetApp",
                "kCGWindowName": "另一个进程同名窗口",
                "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1440, "Height": 900},
                "kCGWindowLayer": 0,
                "kCGWindowIsOnscreen": True,
                "kCGWindowAlpha": 1,
            },
        ]
    )

    candidate = discovery.get_primary_window_for_process(process_id=200)

    assert candidate is not None
    assert candidate.window_id == 11


def test_get_primary_window_for_process_matches_localized_alias() -> None:
    discovery = MacOSWindowDiscovery()
    discovery.is_available = False
    discovery.list_windows = lambda: discovery._convert_raw_windows(
        [
            {
                "kCGWindowNumber": 21,
                "kCGWindowOwnerPID": 300,
                "kCGWindowOwnerName": "WeChat",
                "kCGWindowName": "微信聊天窗口",
                "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1200, "Height": 800},
                "kCGWindowLayer": 0,
                "kCGWindowIsOnscreen": True,
                "kCGWindowAlpha": 1,
            }
        ]
    )

    candidate = discovery.get_primary_window_for_process(process_name="微信")

    assert candidate is not None
    assert candidate.process_name == "WeChat"


def test_get_primary_window_for_process_falls_back_to_partial_name_match() -> None:
    discovery = MacOSWindowDiscovery()
    discovery.is_available = False
    discovery.list_windows = lambda: discovery._convert_raw_windows(
        [
            {
                "kCGWindowNumber": 31,
                "kCGWindowOwnerPID": 400,
                "kCGWindowOwnerName": "Google Chrome Helper",
                "kCGWindowName": "辅助进程窗口",
                "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 400, "Height": 300},
                "kCGWindowLayer": 0,
                "kCGWindowIsOnscreen": True,
                "kCGWindowAlpha": 1,
            },
            {
                "kCGWindowNumber": 32,
                "kCGWindowOwnerPID": 401,
                "kCGWindowOwnerName": "Google Chrome",
                "kCGWindowName": "价格页",
                "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1440, "Height": 900},
                "kCGWindowLayer": 0,
                "kCGWindowIsOnscreen": True,
                "kCGWindowAlpha": 1,
            },
        ]
    )

    candidate = discovery.get_primary_window_for_process(process_name="chrome")

    assert candidate is not None
    assert candidate.window_id == 32


def test_windows_backend_exposes_activate_process_stub() -> None:
    discovery = WindowsWindowDiscovery()
    assert discovery.activate_process(process_name="WeChat") is False
