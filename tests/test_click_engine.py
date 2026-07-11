"""Tests for src/click_engine.py.

CGEventPost is stubbed with a recorder in EVERY test here — the suite must
never post real synthetic input to the OS. Event *creation* stays real
(harmless) so we can assert on the created events' coordinates and types.
"""

import threading
import time

import pytest
from Quartz import CGEventGetLocation, kCGEventLeftMouseDown, kCGEventLeftMouseUp, \
    kCGEventLeftMouseDragged, kCGEventMouseMoved, CGEventGetType

import src.click_engine as ce_mod
from src.click_engine import ClickEngine, ClickType
from src.screen_capture import WindowInfo


@pytest.fixture()
def posted(monkeypatch):
    """Stub CGEventPost → record (tap, event) instead of posting to the OS."""
    events = []
    monkeypatch.setattr(ce_mod, "CGEventPost", lambda tap, ev: events.append((tap, ev)))
    return events


def fake_window(x=100, y=200, w=390, h=844):
    return WindowInfo(window_id=1, owner_name="iPhone Mirroring",
                      window_name="iPhone", owner_pid=999,
                      bounds={"X": x, "Y": y, "Width": w, "Height": h},
                      is_on_screen=True)


def locations(events):
    out = []
    for _tap, ev in events:
        loc = CGEventGetLocation(ev)
        out.append((loc.x, loc.y))
    return out


def types(events):
    return [CGEventGetType(ev) for _tap, ev in events]


class TestClickAt:
    def test_single_click_posts_down_up_at_window_offset(self, posted):
        eng = ClickEngine()
        ok = eng.click_at(50, 60, window=fake_window(x=100, y=200))
        assert ok is True
        assert types(posted) == [kCGEventLeftMouseDown, kCGEventLeftMouseUp]
        # window-relative (50,60) + window origin (100,200) = absolute (150,260)
        assert locations(posted) == [(150.0, 260.0), (150.0, 260.0)]

    def test_double_click_posts_four_events(self, posted):
        eng = ClickEngine()
        assert eng.click_at(1, 2, click_type=ClickType.DOUBLE, window=fake_window())
        assert types(posted) == [kCGEventLeftMouseDown, kCGEventLeftMouseUp,
                                 kCGEventLeftMouseDown, kCGEventLeftMouseUp]

    def test_long_press_holds_for_duration(self, posted):
        eng = ClickEngine()
        t0 = time.monotonic()
        assert eng.click_at(1, 2, click_type=ClickType.LONG_PRESS,
                            duration_ms=150, window=fake_window())
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.14
        assert types(posted) == [kCGEventLeftMouseDown, kCGEventLeftMouseUp]

    def test_long_press_interruptible_by_stop_event(self, posted):
        eng = ClickEngine()
        stop = threading.Event()
        stop.set()  # already stopped → hold returns immediately
        t0 = time.monotonic()
        assert eng.click_at(1, 2, click_type=ClickType.LONG_PRESS,
                            duration_ms=5000, window=fake_window(),
                            stop_event=stop)
        assert time.monotonic() - t0 < 1.0  # did NOT hold 5s
        # mouse-up must still be delivered (no stuck button / thread zombie)
        assert types(posted) == [kCGEventLeftMouseDown, kCGEventLeftMouseUp]

    def test_background_click_restores_cursor(self, posted):
        eng = ClickEngine()
        assert eng.click_at(5, 5, window=fake_window(), background=True)
        # down, up, then a MouseMoved event restoring the original position
        assert types(posted) == [kCGEventLeftMouseDown, kCGEventLeftMouseUp,
                                 kCGEventMouseMoved]

    def test_inactive_engine_refuses(self, posted):
        eng = ClickEngine()
        eng.deactivate()
        assert eng.click_at(1, 1, window=fake_window()) is False
        assert posted == []
        eng.activate()
        assert eng.click_at(1, 1, window=fake_window()) is True

    def test_no_window_refuses(self, posted):
        eng = ClickEngine()   # fresh ScreenCapture → no cached window
        assert eng.click_at(1, 1) is False
        assert posted == []


class TestExecuteAtAbsolute:
    def test_absolute_coordinates_used_verbatim(self, posted):
        eng = ClickEngine()
        assert eng.execute_at_absolute(640, 480)
        assert locations(posted) == [(640.0, 480.0), (640.0, 480.0)]

    def test_inactive_refuses(self, posted):
        eng = ClickEngine()
        eng.deactivate()
        assert eng.execute_at_absolute(1, 1) is False
        assert posted == []


class TestSwipe:
    def test_swipe_posts_down_drags_up(self, posted):
        eng = ClickEngine()
        ok = eng.swipe(10, 100, 10, 20, duration_ms=30,
                       window=fake_window(x=0, y=0), steps=5)
        assert ok is True
        ts = types(posted)
        assert ts[0] == kCGEventLeftMouseDown
        assert ts[-1] == kCGEventLeftMouseUp
        assert ts[1:-1] == [kCGEventLeftMouseDragged] * 5
        # last drag + up land on the end point
        assert locations(posted)[-1] == (10.0, 20.0)

    def test_swipe_no_window_refuses(self, posted):
        eng = ClickEngine()
        assert eng.swipe(0, 0, 1, 1) is False
        assert posted == []

    def test_swipe_stop_event_short_circuits_drags(self, posted):
        eng = ClickEngine()
        stop = threading.Event()
        stop.set()
        assert eng.swipe(0, 0, 100, 100, duration_ms=1000,
                         window=fake_window(x=0, y=0), steps=50,
                         stop_event=stop)
        # down + up only (drag loop broke immediately) → button not left stuck
        ts = types(posted)
        assert ts[0] == kCGEventLeftMouseDown
        assert ts[-1] == kCGEventLeftMouseUp
        assert len(ts) <= 3


class TestPermissions:
    def test_has_post_event_permission_returns_bool(self):
        assert isinstance(ClickEngine.has_post_event_permission(), bool)
