"""
Project persistence module.
Auto-saves and auto-loads all project data (screenshots, timeline, settings)
so nothing is ever lost between sessions.
"""

import os
import json
import cv2
import numpy as np
from typing import Optional
from dataclasses import dataclass

from src.timeline import Timeline


PROJECTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "projects")
DEFAULT_PROJECT = "default"


@dataclass
class ProjectSettings:
    threshold: float = 0.85
    monitor_interval_ms: int = 500

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "monitor_interval_ms": self.monitor_interval_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectSettings":
        return cls(
            threshold=data.get("threshold", 0.85),
            monitor_interval_ms=data.get("monitor_interval_ms", 500),
        )


class Project:
    """
    Manages a project folder containing:
      - reference.png  (the reference screenshot)
      - timeline.json  (the click timeline)
      - settings.json  (threshold, interval, etc.)
    """

    def __init__(self, name: str = DEFAULT_PROJECT):
        self.name = name
        self._dir = os.path.join(PROJECTS_DIR, name)
        os.makedirs(self._dir, exist_ok=True)

    @property
    def directory(self) -> str:
        return self._dir

    @property
    def reference_path(self) -> str:
        return os.path.join(self._dir, "reference.png")

    @property
    def timeline_path(self) -> str:
        return os.path.join(self._dir, "timeline.json")

    @property
    def settings_path(self) -> str:
        return os.path.join(self._dir, "settings.json")

    def has_reference(self) -> bool:
        return os.path.exists(self.reference_path)

    def has_timeline(self) -> bool:
        return os.path.exists(self.timeline_path)

    def has_settings(self) -> bool:
        return os.path.exists(self.settings_path)

    # ── Reference Screenshot ──

    def save_reference(self, image: np.ndarray) -> bool:
        """Save the reference screenshot."""
        try:
            cv2.imwrite(self.reference_path, image)
            return True
        except Exception:
            return False

    def load_reference(self) -> Optional[np.ndarray]:
        """Load the saved reference screenshot."""
        if not self.has_reference():
            return None
        try:
            return cv2.imread(self.reference_path)
        except Exception:
            return None

    # ── Per-Action Screenshots ──

    @property
    def screenshots_dir(self) -> str:
        d = os.path.join(self._dir, "screenshots")
        os.makedirs(d, exist_ok=True)
        return d

    def save_action_screenshot(self, index: int, image: np.ndarray) -> str:
        """Save a screenshot for a specific click action. Returns the file path.
        Uses a unique timestamp-based name to avoid conflicts on reorder/edit."""
        import time as _time
        unique_id = f"{index}_{int(_time.time() * 1000)}"
        path = os.path.join(self.screenshots_dir, f"action_{unique_id}.png")
        cv2.imwrite(path, image)
        return path

    def load_action_screenshot(self, path: str) -> Optional[np.ndarray]:
        """Load a per-action screenshot by path."""
        if not path or not os.path.exists(path):
            return None
        try:
            return cv2.imread(path)
        except Exception:
            return None

    # ── Timeline ──

    def save_timeline(self, timeline: Timeline) -> bool:
        """Save the timeline."""
        try:
            timeline.save(self.timeline_path)
            return True
        except Exception:
            return False

    def load_timeline(self) -> Optional[Timeline]:
        """Load the saved timeline."""
        if not self.has_timeline():
            return None
        try:
            return Timeline.load(self.timeline_path)
        except Exception:
            return None

    # ── Settings ──

    def save_settings(self, settings: ProjectSettings) -> bool:
        """Save project settings."""
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(settings.to_dict(), f, indent=2)
            return True
        except Exception:
            return False

    def load_settings(self) -> ProjectSettings:
        """Load project settings (returns defaults if none saved)."""
        if not self.has_settings():
            return ProjectSettings()
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ProjectSettings.from_dict(data)
        except Exception:
            return ProjectSettings()

    # ── List all projects ──

    @staticmethod
    def list_projects() -> list:
        """List all available project names."""
        if not os.path.exists(PROJECTS_DIR):
            return []
        return [d for d in os.listdir(PROJECTS_DIR)
                if os.path.isdir(os.path.join(PROJECTS_DIR, d))]
