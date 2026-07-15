"""GUI smoke tests — real MainWindow, offscreen Qt platform.

- Projects are routed to a temp dir (never touches the real projects/).
- cwd is a temp dir so the AppLogger 'logs/' output stays out of the repo.
- CGEventPost is stubbed so nothing can ever click the real screen.
"""

import json
import os

import numpy as np
import pytest

import src.click_engine as ce_mod
import src.project as project_mod
import src.tracking as tracking
from src.timeline import ClickAction


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def main_window(qapp, tmp_path, monkeypatch):
    # Isolate side effects
    monkeypatch.setattr(project_mod, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.chdir(tmp_path)  # logs/ goes here
    monkeypatch.setattr(ce_mod, "CGEventPost", lambda *a: None)  # absolute no-click guard
    monkeypatch.setenv("AUTOCLICKER_TRACKS", str(tmp_path / "tracks.jsonl"))
    tracking._reset_for_tests()

    from src.gui.main_window import MainWindow
    win = MainWindow()
    yield win
    win.close()
    qapp.processEvents()


def read_tracks(tmp_path):
    p = tmp_path / "tracks.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


class TestStartup:
    def test_window_constructs(self, main_window):
        assert main_window.windowTitle() == "iOS Auto-Clicker"
        assert main_window._table.rowCount() == len(main_window._timeline.actions)

    def test_startup_flow_tracked(self, main_window, tmp_path):
        events = [e["event"] for e in read_tracks(tmp_path)]
        # Contract: app.startup — order of first occurrences
        expected = ["app.start", "project.settings.loaded",
                    "project.timeline.loaded", "app.ui.ready",
                    "permissions.checked", "window.detected"]
        firsts = [ev for ev in dict.fromkeys(events) if ev in expected]
        assert firsts == expected

    def test_own_window_not_offered_as_target(self, main_window):
        # Combo must never offer the auto-clicker's own process as a target
        for i in range(main_window._window_picker.count()):
            data = main_window._window_picker.itemData(i) or ""
            assert "iOS Auto-Clicker" not in data.split("::")[1:2]


class TestCaptureFailurePath:
    def test_capture_failure_does_not_crash(self, main_window, monkeypatch):
        """Regression: used to raise AttributeError (self._window_status)."""
        monkeypatch.setattr(main_window._screen_capture, "capture_target",
                            lambda t: None)
        main_window._capture_screen()  # must not raise
        assert "Capture failed" in main_window._status_label.text()
        cats = [e.category.name for e in main_window._logger.get_entries()]
        assert "ERROR" in cats


class TestTimelineEditing:
    def test_add_action_updates_table_and_autosave(self, main_window):
        n0 = main_window._table.rowCount()
        main_window._timeline.add_action(
            ClickAction(delay_ms=10, x=5, y=6, label="smoke"))
        main_window._refresh_table()
        main_window._auto_save()
        assert main_window._table.rowCount() == n0 + 1
        assert os.path.exists(main_window._project.timeline_path)
        saved = json.load(open(main_window._project.timeline_path))
        assert any(a.get("label") == "smoke" for a in saved["actions"])

    def test_enable_toggle_via_checkbox(self, main_window, qapp):
        from PySide6.QtCore import Qt
        main_window._timeline.add_action(
            ClickAction(delay_ms=0, x=1, y=1, label="toggle-me"))
        main_window._refresh_table()
        row = main_window._table.rowCount() - 1
        item = main_window._table.item(row, 0)
        item.setCheckState(Qt.CheckState.Unchecked)
        qapp.processEvents()
        assert main_window._timeline.actions[row].enabled is False

    def test_swap_moves_rows(self, main_window):
        main_window._timeline.clear()
        for lbl in ("first", "second"):
            main_window._timeline.add_action(
                ClickAction(delay_ms=0, x=0, y=0, label=lbl))
        main_window._refresh_table()
        main_window._table.selectRow(1)
        main_window._move_up()
        assert [a.label for a in main_window._timeline.actions] == \
               ["second", "first"]


class TestProjectSwitching:
    def test_new_project_isolated_state(self, main_window):
        main_window._timeline.add_action(
            ClickAction(delay_ms=0, x=0, y=0, label="in-default"))
        main_window._auto_save()
        main_window._load_project("second-project", fresh=True)
        assert main_window._project.name == "second-project"
        assert main_window._timeline.actions == []
        # switch back restores the saved timeline
        main_window._load_project("default")
        assert any(a.label == "in-default"
                   for a in main_window._timeline.actions)


class TestScaling:
    def test_scale_to_window_retina_2x(self, main_window, tmp_path):
        """Coords picked on a 2x screenshot must be halved for a 1x window."""
        import cv2
        from src.screen_capture import WindowInfo
        ref = np.zeros((200, 100, 3), dtype=np.uint8)  # 100x200 image
        p = str(tmp_path / "ref2x.png")
        cv2.imwrite(p, ref)
        action = ClickAction(delay_ms=0, x=50, y=100, screenshot_path=p)
        win = WindowInfo(1, "X", "", {"X": 0, "Y": 0, "Width": 50, "Height": 100}, 1, True)
        assert main_window._scale_to_window(action, win) == (25, 50)

    def test_scale_no_ref_passthrough(self, main_window):
        from src.screen_capture import WindowInfo
        action = ClickAction(delay_ms=0, x=7, y=8)
        win = WindowInfo(1, "X", "", {"X": 0, "Y": 0, "Width": 0, "Height": 0}, 1, True)
        assert main_window._scale_to_window(action, win) == (7, 8)
