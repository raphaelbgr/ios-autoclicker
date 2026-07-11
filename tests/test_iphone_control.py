"""Tests for src/iphone_control.py — AppleScript command construction.

subprocess.run is stubbed in every test: no real AppleScript is executed,
no real app is activated.
"""

import subprocess

import pytest

import src.iphone_control as ic


@pytest.fixture()
def calls(monkeypatch):
    """Record osascript invocations; pretend they succeed."""
    recorded = []

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        recorded.append(cmd)
        return FakeResult()

    monkeypatch.setattr(ic.subprocess, "run", fake_run)
    return recorded


def scripts(calls):
    return [c[2] for c in calls]  # ["osascript", "-e", script]


class TestSendCommand:
    def test_home_clicks_menu_item(self, calls):
        assert ic.send_command("home") is True
        assert len(calls) == 2  # activate + menu click
        assert 'tell application "iPhone Mirroring" to activate' in scripts(calls)[0]
        assert 'menu item "Home Screen"' in scripts(calls)[1]
        assert 'menu bar item "View"' in scripts(calls)[1]

    def test_app_switcher_and_spotlight_mapping(self, calls):
        ic.send_command("app_switcher")
        ic.send_command("spotlight")
        joined = "\n".join(scripts(calls))
        assert 'menu item "App Switcher"' in joined
        assert 'menu item "Spotlight"' in joined

    def test_unknown_command_refused_without_calls(self, calls):
        assert ic.send_command("warp_drive") is False
        assert calls == []

    def test_custom_process_name(self, calls):
        ic.send_command("home", process_name="Custom Proc")
        assert 'process "Custom Proc"' in scripts(calls)[1]


class TestTypeText:
    def test_types_and_presses_return(self, calls):
        assert ic.type_text("Sky Force") is True
        script = scripts(calls)[1]
        assert 'keystroke "Sky Force"' in script
        assert "key code 36" in script

    def test_no_return(self, calls):
        ic.type_text("abc", press_return=False)
        assert "key code 36" not in scripts(calls)[1]

    def test_escapes_quotes_and_backslashes(self, calls):
        ic.type_text('say "hi" \\ bye')
        script = scripts(calls)[1]
        assert 'keystroke "say \\"hi\\" \\\\ bye"' in script


class TestRunFailurePaths:
    def test_failed_osascript_returns_false(self, monkeypatch):
        class Fail:
            returncode = 1
        monkeypatch.setattr(ic.subprocess, "run", lambda *a, **k: Fail())
        assert ic.activate() is False

    def test_exception_returns_false(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("no osascript")
        monkeypatch.setattr(ic.subprocess, "run", boom)
        assert ic.send_command("home") is False
