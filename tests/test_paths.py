"""Tests for src/paths.py — sandbox-safe data-dir resolution."""

import os
import sys

import src.paths as paths


class TestAppDataDir:
    def test_dev_uses_repo_root(self, monkeypatch):
        monkeypatch.delenv("AUTOCLICKER_DATA_DIR", raising=False)
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(paths.__file__)))
        assert paths.app_data_dir() == repo_root

    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTOCLICKER_DATA_DIR", str(tmp_path))
        # even when frozen, the override takes precedence
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert paths.app_data_dir() == str(tmp_path)

    def test_frozen_uses_application_support(self, monkeypatch):
        monkeypatch.delenv("AUTOCLICKER_DATA_DIR", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        expected = os.path.join(
            os.path.expanduser("~"), "Library", "Application Support",
            paths.APP_DIR_NAME,
        )
        assert paths.app_data_dir() == expected

    def test_frozen_path_is_container_safe_under_sandbox(self, monkeypatch):
        """When sandboxed, expanduser('~') is the container, so the data dir
        lands inside it. Simulate the sandbox by pointing HOME at a container."""
        monkeypatch.delenv("AUTOCLICKER_DATA_DIR", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        container = "/Users/x/Library/Containers/br.com.raphaelbgr.autoclicker/Data"
        monkeypatch.setenv("HOME", container)
        assert paths.app_data_dir().startswith(container)


class TestDerivedDirs:
    def test_derived_dirs_under_base(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTOCLICKER_DATA_DIR", str(tmp_path))
        assert paths.projects_dir() == os.path.join(str(tmp_path), "projects")
        assert paths.logs_dir() == os.path.join(str(tmp_path), "logs")
        assert paths.tracks_file() == os.path.join(str(tmp_path), "tracks", "tracks.jsonl")
