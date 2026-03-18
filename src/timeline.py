"""
Timeline module for programmable click sequences.
Defines data models for click actions and provides execution logic.
"""

import json
import time
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Callable
from enum import Enum

from src.click_engine import ClickType


@dataclass
class ClickAction:
    """A single click action triggered by screen matching.

    Each action has its own reference screenshot and similarity threshold.
    When the screen matches this action's screenshot >= threshold,
    OR when any of match_texts are found on screen (OCR),
    it waits delay_ms then clicks at (x, y).
    """
    delay_ms: int           # Delay after screen match before clicking
    x: int                  # X coordinate relative to window
    y: int                  # Y coordinate relative to window
    click_type: str = ClickType.SINGLE  # "single", "double", "long_press"
    duration_ms: int = 100  # Duration for long press
    label: str = ""         # User-friendly label
    screenshot_path: str = ""  # Path to per-click reference screenshot
    threshold: float = 0.85   # Per-action similarity threshold (0.0–1.0)
    match_texts: str = ""     # Comma-separated text patterns for OCR matching (OR logic)
    enabled: bool = True      # Whether this action is active
    repeat_count: int = 1     # Number of clicks to fire (spaced within 1s window)

    def to_dict(self) -> dict:
        d = {
            "delay_ms": self.delay_ms,
            "x": self.x,
            "y": self.y,
            "click_type": self.click_type,
            "duration_ms": self.duration_ms,
            "label": self.label,
            "threshold": self.threshold,
            "enabled": self.enabled,
            "repeat_count": self.repeat_count,
        }
        if self.screenshot_path:
            d["screenshot_path"] = self.screenshot_path
        if self.match_texts:
            d["match_texts"] = self.match_texts
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ClickAction":
        # Backward compat: old files use "timestamp_ms" instead of "delay_ms"
        delay = data.get("delay_ms", data.get("timestamp_ms", 0))
        return cls(
            delay_ms=delay,
            x=data["x"],
            y=data["y"],
            click_type=data.get("click_type", ClickType.SINGLE),
            duration_ms=data.get("duration_ms", 100),
            label=data.get("label", ""),
            screenshot_path=data.get("screenshot_path", ""),
            threshold=data.get("threshold", 0.85),
            match_texts=data.get("match_texts", ""),
            enabled=data.get("enabled", True),
            repeat_count=data.get("repeat_count", 1),
        )


class Timeline:
    """
    A sequence of click actions to be executed in order.
    Actions are sorted by timestamp_ms.
    """

    def __init__(self, name: str = "Untitled Timeline"):
        self.name = name
        self._actions: List[ClickAction] = []
        self._loop: bool = False
        self._loop_count: int = 1  # 0 = infinite

    @property
    def actions(self) -> List[ClickAction]:
        return list(self._actions)

    @property
    def loop(self) -> bool:
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def loop_count(self) -> int:
        return self._loop_count

    @loop_count.setter
    def loop_count(self, value: int):
        self._loop_count = max(0, value)

    @property
    def total_duration_ms(self) -> int:
        if not self._actions:
            return 0
        return sum(a.delay_ms + a.duration_ms for a in self._actions)

    def add_action(self, action: ClickAction):
        """Add a click action to the end of the list."""
        self._actions.append(action)

    def remove_action(self, index: int) -> Optional[ClickAction]:
        """Remove action at index."""
        if 0 <= index < len(self._actions):
            return self._actions.pop(index)
        return None

    def update_action(self, index: int, action: ClickAction):
        """Replace action at index (keeps position)."""
        if 0 <= index < len(self._actions):
            self._actions[index] = action

    def clear(self):
        """Remove all actions."""
        self._actions.clear()



    def swap_actions(self, index_a: int, index_b: int):
        """Swap two actions by index (for manual reordering)."""
        if (0 <= index_a < len(self._actions) and
                0 <= index_b < len(self._actions)):
            self._actions[index_a], self._actions[index_b] = (
                self._actions[index_b], self._actions[index_a]
            )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "loop": self._loop,
            "loop_count": self._loop_count,
            "actions": [a.to_dict() for a in self._actions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Timeline":
        tl = cls(name=data.get("name", "Untitled"))
        tl._loop = data.get("loop", False)
        tl._loop_count = data.get("loop_count", 1)
        for action_data in data.get("actions", []):
            tl._actions.append(ClickAction.from_dict(action_data))
        return tl

    def save(self, filepath: str):
        """Save timeline to a JSON file."""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath: str) -> "Timeline":
        """Load timeline from a JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


class TimelineExecutor:
    """
    Executes a Timeline by firing click actions at the correct timestamps.
    Runs in a background thread for non-blocking operation.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = False
        self._on_action: Optional[Callable[[ClickAction, int], None]] = None
        self._on_complete: Optional[Callable[[], None]] = None
        self._on_loop: Optional[Callable[[int], None]] = None
        self._current_action_index: int = 0
        self._current_loop: int = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_paused(self) -> bool:
        return self._paused

    def set_callbacks(self,
                      on_action: Optional[Callable[[ClickAction, int], None]] = None,
                      on_complete: Optional[Callable[[], None]] = None,
                      on_loop: Optional[Callable[[int], None]] = None):
        """
        Set callback functions.
        on_action(action, index): called when each action is about to execute
        on_complete(): called when timeline finishes
        on_loop(loop_number): called at the start of each loop iteration
        """
        self._on_action = on_action
        self._on_complete = on_complete
        self._on_loop = on_loop

    def start(self, timeline: Timeline, click_callback: Callable[[ClickAction], bool]):
        """
        Start executing the timeline.

        Args:
            timeline: The timeline to execute
            click_callback: Function to call to execute each click action.
                          Should return True on success.
        """
        if self.is_running:
            self.stop()

        self._stop_event.clear()
        self._paused = False
        self._current_action_index = 0
        self._current_loop = 0

        self._thread = threading.Thread(
            target=self._run,
            args=(timeline, click_callback),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """Stop the timeline execution."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def _run(self, timeline: Timeline, click_callback: Callable[[ClickAction], bool]):
        """Background thread: execute timeline actions with timing."""
        actions = timeline.actions
        if not actions:
            if self._on_complete:
                self._on_complete()
            return

        total_loops = timeline.loop_count if timeline.loop else 1
        loop_num = 0

        while not self._stop_event.is_set():
            loop_num += 1
            self._current_loop = loop_num

            if self._on_loop:
                self._on_loop(loop_num)

            start_time = time.monotonic()

            for idx, action in enumerate(actions):
                if self._stop_event.is_set():
                    return

                # Wait for unpause
                while self._paused and not self._stop_event.is_set():
                    time.sleep(0.05)

                if self._stop_event.is_set():
                    return

                self._current_action_index = idx

                # Wait until the action's timestamp
                target_time = start_time + (action.delay_ms / 1000.0)
                while time.monotonic() < target_time:
                    if self._stop_event.is_set():
                        return
                    # Wait in small increments for responsiveness
                    remaining = target_time - time.monotonic()
                    if remaining > 0:
                        time.sleep(min(remaining, 0.01))

                # Execute the action
                if self._on_action:
                    self._on_action(action, idx)
                click_callback(action)

            # Check if we should loop
            if not timeline.loop:
                break
            if total_loops > 0 and loop_num >= total_loops:
                break

        if self._on_complete:
            self._on_complete()
