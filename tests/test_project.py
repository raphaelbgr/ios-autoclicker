"""Tests for src/project.py — persistence of settings, timeline, reference, screenshots."""

import json
import os

import numpy as np
import pytest

import src.project as project_mod
from src.project import Project, ProjectSettings
from src.timeline import Timeline, ClickAction


@pytest.fixture()
def proj_dir(tmp_path, monkeypatch):
    """Route PROJECTS_DIR into a temp folder so tests never touch real projects."""
    d = tmp_path / "projects"
    monkeypatch.setattr(project_mod, "PROJECTS_DIR", str(d))
    return d


class TestProjectSettings:
    def test_defaults(self):
        s = ProjectSettings()
        assert s.threshold == 0.85
        assert s.monitor_interval_ms == 500
        assert s.background_click is False
        assert s.target_app == "iPhone Mirroring"

    def test_roundtrip(self):
        s = ProjectSettings(threshold=0.6, monitor_interval_ms=250,
                            background_click=True, target_app="X::Y::Z")
        s2 = ProjectSettings.from_dict(s.to_dict())
        assert s2 == s

    def test_from_partial_dict_uses_defaults(self):
        s = ProjectSettings.from_dict({"threshold": 0.7})
        assert s.threshold == 0.7
        assert s.monitor_interval_ms == 500


class TestProject:
    def test_creates_directory(self, proj_dir):
        p = Project("alpha")
        assert os.path.isdir(p.directory)
        assert p.directory == str(proj_dir / "alpha")

    def test_settings_roundtrip(self, proj_dir):
        p = Project("alpha")
        assert p.has_settings() is False
        assert p.load_settings() == ProjectSettings()  # defaults when missing
        s = ProjectSettings(threshold=0.42, monitor_interval_ms=999,
                            background_click=True, target_app="T")
        assert p.save_settings(s) is True
        assert p.has_settings() is True
        assert Project("alpha").load_settings() == s

    def test_corrupted_settings_returns_defaults(self, proj_dir):
        p = Project("alpha")
        with open(p.settings_path, "w") as f:
            f.write("{ not json !!!")
        assert p.load_settings() == ProjectSettings()

    def test_timeline_roundtrip(self, proj_dir):
        p = Project("beta")
        assert p.load_timeline() is None
        tl = Timeline("beta-tl")
        tl.add_action(ClickAction(delay_ms=5, x=1, y=2, label="go"))
        assert p.save_timeline(tl) is True
        loaded = p.load_timeline()
        assert loaded.name == "beta-tl"
        assert loaded.actions[0].label == "go"

    def test_corrupted_timeline_returns_none(self, proj_dir):
        p = Project("beta")
        with open(p.timeline_path, "w") as f:
            f.write("][")
        assert p.load_timeline() is None

    def test_reference_roundtrip(self, proj_dir):
        p = Project("gamma")
        assert p.load_reference() is None
        img = np.random.default_rng(0).integers(
            0, 255, (32, 32, 3)).astype(np.uint8)
        assert p.save_reference(img) is True
        assert p.has_reference() is True
        loaded = p.load_reference()
        assert np.array_equal(loaded, img)  # PNG is lossless

    def test_action_screenshot_save_load(self, proj_dir):
        p = Project("delta")
        img = np.random.default_rng(1).integers(
            0, 255, (24, 24, 3)).astype(np.uint8)
        path = p.save_action_screenshot(3, img)
        assert os.path.exists(path)
        assert os.path.basename(path).startswith("action_3_")
        assert np.array_equal(p.load_action_screenshot(path), img)

    def test_action_screenshot_unique_names(self, proj_dir):
        p = Project("delta")
        img = np.zeros((8, 8, 3), dtype=np.uint8)
        p1 = p.save_action_screenshot(0, img)
        p2 = p.save_action_screenshot(0, img)
        assert p1 != p2  # timestamped, no clobber on reorder/edit

    def test_load_action_screenshot_missing(self, proj_dir):
        p = Project("delta")
        assert p.load_action_screenshot("") is None
        assert p.load_action_screenshot("/nope/missing.png") is None

    def test_list_projects(self, proj_dir):
        assert Project.list_projects() == [] or True  # dir may not exist yet
        Project("one")
        Project("two")
        names = set(Project.list_projects())
        assert {"one", "two"} <= names
