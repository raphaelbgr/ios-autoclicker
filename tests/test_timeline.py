"""Tests for src/timeline.py — ClickAction / Timeline serialization + TimelineExecutor."""

import json
import os
import threading
import time

import pytest

from src.click_engine import ClickType
from src.timeline import ClickAction, Timeline, TimelineExecutor


# ──────────────────────────────────────────────────────────────
#  ClickAction serialization
# ──────────────────────────────────────────────────────────────

class TestClickAction:
    def test_roundtrip_minimal(self):
        a = ClickAction(delay_ms=100, x=10, y=20)
        b = ClickAction.from_dict(a.to_dict())
        assert (b.delay_ms, b.x, b.y) == (100, 10, 20)
        assert b.click_type == ClickType.SINGLE
        assert b.enabled is True
        assert b.threshold == 0.85
        assert b.repeat_count == 1
        assert b.trigger_type == "recognition"
        assert b.action_type == "click"

    def test_roundtrip_full_click_fields(self):
        a = ClickAction(
            delay_ms=250, x=181, y=696,
            click_type=ClickType.LONG_PRESS, duration_ms=5000,
            label="Tap Play", screenshot_path="projects/p/screenshots/s.png",
            threshold=0.65, match_texts="PLAY, START",
            enabled=False, repeat_count=7,
        )
        b = ClickAction.from_dict(a.to_dict())
        assert b == a

    def test_roundtrip_app_action_fields(self):
        a = ClickAction(
            delay_ms=0, x=0, y=0, action_type="open_app",
            open_method="spotlight", app_name="Sky Force",
            post_delay_ms=1500, close_method="home",
        )
        d = a.to_dict()
        # Non-click actions must persist lifecycle fields
        assert d["action_type"] == "open_app"
        assert d["app_name"] == "Sky Force"
        assert d["post_delay_ms"] == 1500
        b = ClickAction.from_dict(d)
        assert b == a

    def test_click_action_omits_app_fields(self):
        d = ClickAction(delay_ms=0, x=1, y=2).to_dict()
        assert "action_type" not in d
        assert "app_name" not in d
        assert "trigger_type" not in d

    def test_roundtrip_after_trigger_fields(self):
        a = ClickAction(delay_ms=1500, x=5, y=6,
                        trigger_type="after_trigger", after_index=3)
        d = a.to_dict()
        assert d["trigger_type"] == "after_trigger"
        assert d["after_index"] == 3
        b = ClickAction.from_dict(d)
        assert b.trigger_type == "after_trigger"
        assert b.after_index == 3

    def test_backward_compat_timestamp_ms(self):
        b = ClickAction.from_dict({"timestamp_ms": 777, "x": 1, "y": 2})
        assert b.delay_ms == 777

    def test_optional_screenshot_and_texts_omitted_when_empty(self):
        d = ClickAction(delay_ms=0, x=0, y=0).to_dict()
        assert "screenshot_path" not in d
        assert "match_texts" not in d


# ──────────────────────────────────────────────────────────────
#  Timeline container
# ──────────────────────────────────────────────────────────────

class TestTimeline:
    def _mk(self, n=3):
        tl = Timeline("T")
        for i in range(n):
            tl.add_action(ClickAction(delay_ms=i * 10, x=i, y=i, label=f"a{i}"))
        return tl

    def test_add_remove_update_clear(self):
        tl = self._mk()
        assert len(tl.actions) == 3
        removed = tl.remove_action(1)
        assert removed.label == "a1"
        assert [a.label for a in tl.actions] == ["a0", "a2"]
        tl.update_action(0, ClickAction(delay_ms=0, x=9, y=9, label="new"))
        assert tl.actions[0].label == "new"
        assert tl.remove_action(99) is None
        tl.clear()
        assert tl.actions == []

    def test_swap_actions(self):
        tl = self._mk()
        tl.swap_actions(0, 2)
        assert [a.label for a in tl.actions] == ["a2", "a1", "a0"]
        tl.swap_actions(0, 99)  # out of range → no-op
        assert [a.label for a in tl.actions] == ["a2", "a1", "a0"]

    def test_loop_count_clamped(self):
        tl = self._mk(0)
        tl.loop_count = -5
        assert tl.loop_count == 0
        tl.loop = True
        assert tl.loop is True

    def test_total_duration(self):
        tl = Timeline()
        tl.add_action(ClickAction(delay_ms=100, x=0, y=0, duration_ms=50))
        tl.add_action(ClickAction(delay_ms=200, x=0, y=0, duration_ms=100))
        assert tl.total_duration_ms == 450

    def test_json_file_roundtrip(self, tmp_path):
        tl = self._mk()
        tl.loop = True
        tl.loop_count = 4
        p = tmp_path / "tl.json"
        tl.save(str(p))
        loaded = Timeline.load(str(p))
        assert loaded.name == "T"
        assert loaded.loop is True
        assert loaded.loop_count == 4
        assert [a.label for a in loaded.actions] == ["a0", "a1", "a2"]

    def test_load_real_shipped_timelines(self):
        """The two timeline JSONs shipped in the repo must still parse."""
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for fname in ("My Timeline.json", "Sky force reloaded clicks.json"):
            path = os.path.join(root, fname)
            if not os.path.exists(path):
                pytest.skip(f"{fname} not present")
            tl = Timeline.load(path)
            assert isinstance(tl.actions, list)
            assert len(tl.actions) > 0


# ──────────────────────────────────────────────────────────────
#  TimelineExecutor
# ──────────────────────────────────────────────────────────────

class TestTimelineExecutor:
    def _timeline(self, delays=(0, 30)):
        tl = Timeline("exec")
        for i, d in enumerate(delays):
            tl.add_action(ClickAction(delay_ms=d, x=i, y=i, label=f"a{i}"))
        return tl

    def test_executes_all_actions_in_order(self):
        tl = self._timeline()
        fired, done = [], threading.Event()
        ex = TimelineExecutor()
        ex.set_callbacks(on_complete=done.set)
        ex.start(tl, lambda a: fired.append(a.label) or True)
        assert done.wait(2.0), "executor did not complete"
        assert fired == ["a0", "a1"]
        assert not ex.is_running or ex._thread.join(1.0) is None

    def test_loop_count(self):
        tl = self._timeline(delays=(0, 1))
        tl.loop = True
        tl.loop_count = 3
        fired, done, loops = [], threading.Event(), []
        ex = TimelineExecutor()
        ex.set_callbacks(on_complete=done.set, on_loop=loops.append)
        ex.start(tl, lambda a: fired.append(a.label) or True)
        assert done.wait(3.0)
        assert len(fired) == 6
        assert loops == [1, 2, 3]

    def test_stop_interrupts(self):
        tl = self._timeline(delays=(0, 5000))  # second action far in the future
        fired = []
        ex = TimelineExecutor()
        ex.start(tl, lambda a: fired.append(a.label) or True)
        time.sleep(0.2)
        ex.stop()
        assert not ex.is_running
        assert fired == ["a0"]

    def test_empty_timeline_completes_immediately(self):
        done = threading.Event()
        ex = TimelineExecutor()
        ex.set_callbacks(on_complete=done.set)
        ex.start(Timeline("empty"), lambda a: True)
        assert done.wait(1.0)

    def test_pause_resume(self):
        """Pause is checkpointed before each action: pausing from inside a0's
        callback deterministically blocks the executor at a1's checkpoint.
        (Note: start() resets pause, so pre-pausing is by-design ineffective.)"""
        tl = self._timeline(delays=(0, 0))
        fired, done = [], threading.Event()
        ex = TimelineExecutor()
        ex.set_callbacks(on_complete=done.set)

        def cb(a):
            fired.append(a.label)
            if a.label == "a0":
                ex.pause()  # pause while executor is inside a0's execution
            return True

        ex.start(tl, cb)
        time.sleep(0.3)
        assert fired == ["a0"]      # a1 held at its pause checkpoint
        assert ex.is_paused
        ex.resume()
        assert done.wait(2.0)
        assert fired == ["a0", "a1"]
        ex.stop()


# ──────────────────────────────────────────────────────────────
#  Self-contained .zip package export/import
# ──────────────────────────────────────────────────────────────

class TestTimelinePackage:
    def _timeline_with_screenshots(self, tmp_path, n=2):
        tl = Timeline("Pkg")
        tl.loop = True
        tl.loop_count = 3
        for i in range(n):
            p = tmp_path / f"shot_{i}.png"
            p.write_bytes(b"PNGDATA-%d" % i)
            tl.add_action(ClickAction(
                delay_ms=100, x=i, y=i, label=f"a{i}", screenshot_path=str(p)))
        return tl

    def test_package_roundtrip(self, tmp_path):
        tl = self._timeline_with_screenshots(tmp_path)
        pkg = tmp_path / "out.zip"
        tl.export_package(str(pkg))

        dest = tmp_path / "imported_shots"
        loaded = Timeline.load_package(str(pkg), str(dest))

        assert loaded.name == "Pkg"
        assert loaded.loop is True
        assert loaded.loop_count == 3
        assert len(loaded.actions) == 2
        for i, a in enumerate(loaded.actions):
            assert os.path.isabs(a.screenshot_path)
            assert a.screenshot_path.startswith(str(dest))
            with open(a.screenshot_path, "rb") as f:
                assert f.read() == b"PNGDATA-%d" % i

    def test_package_is_machine_independent(self, tmp_path):
        """The JSON inside the zip must not contain absolute source paths."""
        import zipfile
        tl = self._timeline_with_screenshots(tmp_path)
        pkg = tmp_path / "out.zip"
        tl.export_package(str(pkg))
        with zipfile.ZipFile(pkg) as zf:
            data = json.loads(zf.read("timeline.json"))
            names = set(zf.namelist())
        for entry in data["actions"]:
            assert entry["screenshot_path"].startswith("screenshots/")
            assert entry["screenshot_path"] in names

    def test_missing_screenshot_not_bundled(self, tmp_path):
        import zipfile
        tl = Timeline("Pkg")
        tl.add_action(ClickAction(
            delay_ms=0, x=1, y=1, screenshot_path="/nonexistent/gone.png"))
        pkg = tmp_path / "out.zip"
        tl.export_package(str(pkg))
        with zipfile.ZipFile(pkg) as zf:
            assert zf.namelist() == ["timeline.json"]
            data = json.loads(zf.read("timeline.json"))
        # original path preserved so a same-machine import still works
        assert data["actions"][0]["screenshot_path"] == "/nonexistent/gone.png"
        loaded = Timeline.load_package(str(pkg), str(tmp_path / "shots"))
        assert loaded.actions[0].screenshot_path == "/nonexistent/gone.png"

    def test_shared_screenshot_deduped(self, tmp_path):
        import zipfile
        p = tmp_path / "shared.png"
        p.write_bytes(b"SHARED")
        tl = Timeline("Pkg")
        for i in range(2):
            tl.add_action(ClickAction(
                delay_ms=0, x=i, y=i, screenshot_path=str(p)))
        pkg = tmp_path / "out.zip"
        tl.export_package(str(pkg))
        with zipfile.ZipFile(pkg) as zf:
            assert sorted(zf.namelist()) == ["screenshots/shared.png", "timeline.json"]
        loaded = Timeline.load_package(str(pkg), str(tmp_path / "shots"))
        assert (loaded.actions[0].screenshot_path
                == loaded.actions[1].screenshot_path)

    def test_zip_slip_cannot_escape_screenshots_dir(self, tmp_path):
        """A crafted archive with a traversal path must not write outside
        screenshots_dir (extraction is by basename)."""
        import zipfile
        evil_member = "screenshots/../evil.png"
        pkg = tmp_path / "evil.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr(evil_member, b"EVIL")
            zf.writestr("timeline.json", json.dumps({
                "name": "Evil", "loop": False, "loop_count": 1,
                "actions": [{"delay_ms": 0, "x": 1, "y": 1,
                             "screenshot_path": evil_member}],
            }))
        dest = tmp_path / "safe" / "shots"
        loaded = Timeline.load_package(str(pkg), str(dest))
        assert not (tmp_path / "safe" / "evil.png").exists()
        assert loaded.actions[0].screenshot_path == str(dest / "evil.png")
        assert (dest / "evil.png").read_bytes() == b"EVIL"

    def test_actions_without_screenshots_roundtrip(self, tmp_path):
        tl = Timeline("NoShots")
        tl.add_action(ClickAction(delay_ms=50, x=5, y=6, label="plain"))
        pkg = tmp_path / "out.zip"
        tl.export_package(str(pkg))
        loaded = Timeline.load_package(str(pkg), str(tmp_path / "shots"))
        assert loaded.actions[0].label == "plain"
        assert loaded.actions[0].screenshot_path == ""
