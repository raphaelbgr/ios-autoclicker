"""Pytest bootstrap for the iOS Auto-Clicker test suite.

- Puts the repo root on sys.path so `src.*` imports resolve.
- Forces Qt into offscreen mode (no windows flash during GUI tests).
- Routes the canonical-v1 tracks stream to a per-session temp file so
  test runs never pollute the real tracks/tracks.jsonl.
"""

import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "AUTOCLICKER_TRACKS",
    os.path.join(tempfile.mkdtemp(prefix="autoclicker-test-tracks-"), "tracks.jsonl"),
)
