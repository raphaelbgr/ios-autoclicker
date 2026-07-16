"""
Filesystem locations for the iOS Auto-Clicker.

All writable user data (projects, logs, tracks) must live somewhere the app can
write in every distribution mode:

  * Running from source (development): the repo root — keeps the existing
    on-disk layout and dev/test workflow unchanged.
  * Bundled / frozen (py2app, Briefcase, a future Mac App Store build): the
    per-user Application Support directory. Under the macOS App Sandbox,
    ``os.path.expanduser("~")`` already resolves to the app's container, so this
    path lands inside ``~/Library/Containers/<bundle-id>/Data/Library/Application
    Support/<app>`` automatically — the only location a sandboxed app may write.
    Writing anywhere relative to the (read-only) bundle would be denied.

Override the base directory with the ``AUTOCLICKER_DATA_DIR`` environment
variable (used by the test suite to sandbox runs).

Kept dependency-free (``os`` + ``sys`` only) so any module — including
``tracking.py``, which must not import Qt or cv2 — can use it.
"""

import os
import sys

APP_DIR_NAME = "iOS Auto-Clicker"


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_data_dir() -> str:
    """Base directory for all writable user data.

    ``AUTOCLICKER_DATA_DIR`` wins; then a frozen app uses Application Support
    (container-safe under the sandbox); otherwise the repo root (dev/tests)."""
    override = os.environ.get("AUTOCLICKER_DATA_DIR")
    if override:
        return override
    if getattr(sys, "frozen", False):
        return os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", APP_DIR_NAME
        )
    return _repo_root()


def projects_dir() -> str:
    return os.path.join(app_data_dir(), "projects")


def logs_dir() -> str:
    return os.path.join(app_data_dir(), "logs")


def tracks_file() -> str:
    return os.path.join(app_data_dir(), "tracks", "tracks.jsonl")
