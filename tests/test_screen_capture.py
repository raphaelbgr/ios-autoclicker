"""Tests for src/screen_capture.py — WindowInfo + target-window resolution.

Window enumeration is stubbed where determinism matters; the real Quartz
entire-screen path is exercised too (skipped gracefully when the terminal
lacks Screen Recording permission).
"""

import numpy as np
import pytest

from src.screen_capture import ScreenCapture, WindowInfo


def w(id_, owner, name="", x=0, y=0, width=100, height=100):
    return WindowInfo(window_id=id_, owner_name=owner, window_name=name,
                      bounds={"X": x, "Y": y, "Width": width, "Height": height},
                      owner_pid=id_ * 10, is_on_screen=True)


FAKE_WINDOWS = [
    w(11, "Safari", "Apple"),
    w(22, "iPhone Mirroring", "iPhone de Raphael"),
    w(33, "Terminal", "zsh"),
]


@pytest.fixture()
def sc(monkeypatch):
    cap = ScreenCapture()
    monkeypatch.setattr(cap, "list_windows", lambda: list(FAKE_WINDOWS))
    return cap


class TestWindowInfo:
    def test_properties(self):
        win = w(1, "App", x=10, y=20, width=300, height=400)
        assert (win.x, win.y, win.width, win.height) == (10, 20, 300, 400)
        assert win.is_entire_screen is False

    def test_entire_screen_flag(self):
        win = WindowInfo(0, "[Entire Screen]", "Entire Screen", {}, 0, True)
        assert win.is_entire_screen is True
        assert win.width == 0  # empty bounds default to 0


class TestFindTargetWindow:
    def test_composite_id_match_wins(self, sc):
        found = sc.find_target_window("22::iPhone Mirroring::iPhone de Raphael")
        assert found.window_id == 22
        assert sc.get_cached_window() is found

    def test_composite_falls_back_to_owner_and_name(self, sc):
        # Stale window id (99) but owner+name still present → fallback 1a
        found = sc.find_target_window("99::iPhone Mirroring::iPhone de Raphael")
        assert found.window_id == 22

    def test_composite_falls_back_to_owner_only(self, sc):
        found = sc.find_target_window("99::Safari::Old Tab Title")
        assert found.window_id == 11

    def test_exact_owner_match_case_insensitive(self, sc):
        assert sc.find_target_window("safari").window_id == 11

    def test_substring_owner_match(self, sc):
        assert sc.find_target_window("Mirror").window_id == 22

    def test_iphone_fallback_heuristics(self, monkeypatch):
        cap = ScreenCapture()
        monkeypatch.setattr(cap, "list_windows",
                            lambda: [w(7, "ScreenContinuity Helper")])
        # No exact/substring match for "iPhone Mirroring", but the
        # bundle-ish name contains neither... use 'mirror'/'iphone' heuristic:
        monkeypatch.setattr(cap, "list_windows",
                            lambda: [w(7, "Mirroring Agent")])
        found = cap.find_target_window("iPhone Mirroring")
        assert found is not None and found.window_id == 7

    def test_not_found(self, sc):
        assert sc.find_target_window("NoSuchApp") is None

    def test_entire_screen_pseudo_window(self):
        cap = ScreenCapture()
        found = cap.find_target_window("[Entire Screen]")
        assert found is not None
        assert found.is_entire_screen
        assert found.width > 0 and found.height > 0
        assert cap.get_cached_window() is found


class TestCapture:
    def test_capture_entire_screen_returns_bgr(self):
        cap = ScreenCapture()
        win = cap.find_target_window("[Entire Screen]")
        img = cap.capture_window(win)
        if img is None:
            pytest.skip("Screen Recording permission not granted to this terminal")
        assert isinstance(img, np.ndarray)
        assert img.ndim == 3 and img.shape[2] == 3  # BGR
        assert img.shape[0] > 100 and img.shape[1] > 100

    def test_capture_target_unknown_returns_none(self, sc):
        assert sc.capture_target("NoSuchApp") is None

    def test_permission_check_returns_bool(self):
        assert isinstance(ScreenCapture.check_screen_recording_permission(), bool)


class TestBringToFront:
    def test_entire_screen_is_noop_true(self):
        win = WindowInfo(0, "[Entire Screen]", "Entire Screen", {}, 0, True)
        assert ScreenCapture.bring_window_to_front(win) is True
