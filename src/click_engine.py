"""
Click engine for macOS.
Sends mouse click events to the iPhone Mirroring window using CGEvent via PyObjC.
"""

import time
from typing import Optional
from dataclasses import dataclass

import Quartz
from Quartz import (
    CGEventCreateMouseEvent,
    CGEventPost,
    kCGHIDEventTap,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    CGEventSetIntegerValueField,
    kCGMouseEventClickState,
    CGEventCreate,
    CGEventGetLocation,
    kCGEventMouseMoved,
)
from Quartz.CoreGraphics import CGPointMake

from src.screen_capture import WindowInfo, ScreenCapture


class ClickType:
    SINGLE = "single"
    DOUBLE = "double"
    LONG_PRESS = "long_press"


class ClickEngine:
    """Sends mouse clicks to specific screen coordinates."""

    def __init__(self, screen_capture: Optional[ScreenCapture] = None):
        self._screen_capture = screen_capture or ScreenCapture()
        self._is_active = True

    @property
    def is_active(self) -> bool:
        return self._is_active

    def activate(self):
        self._is_active = True

    def deactivate(self):
        self._is_active = False

    def click_at(self, x: int, y: int, click_type: str = ClickType.SINGLE,
                 duration_ms: int = 100, window: Optional[WindowInfo] = None,
                 background: bool = False, stop_event=None) -> bool:
        """
        Execute a click at the given coordinates.

        Args:
            x: X coordinate relative to the target window
            y: Y coordinate relative to the target window
            click_type: Type of click (single, double, long_press)
            duration_ms: Duration for long press in milliseconds
            window: Target window info (uses cached iPhone Mirroring if None)
            background: If true, sends click directly to the app without moving cursor

        Returns:
            True if click was executed successfully
        """
        if not self._is_active:
            return False

        # Get window info for coordinate conversion
        if window is None:
            window = self._screen_capture.get_cached_window()
            if window is None:
                window = self._screen_capture.find_iphone_mirroring_window()
        if window is None:
            return False

        # Convert window-relative coordinates to absolute screen coordinates
        abs_x = window.x + x
        abs_y = window.y + y

        try:
            if click_type == ClickType.SINGLE:
                self._execute_with_cursor_restore(background, self._single_click, abs_x, abs_y)
            elif click_type == ClickType.DOUBLE:
                self._execute_with_cursor_restore(background, self._double_click, abs_x, abs_y)
            elif click_type == ClickType.LONG_PRESS:
                self._execute_with_cursor_restore(background, self._long_press, abs_x, abs_y, duration_ms, stop_event)
            return True
        except Exception:
            return False

    def execute_at_absolute(self, abs_x: int, abs_y: int,
                            click_type: str = ClickType.SINGLE,
                            duration_ms: int = 100,
                            background: bool = False,
                            stop_event=None) -> bool:
        """Execute a click at absolute screen coordinates."""
        if not self._is_active:
            return False

        try:
            if click_type == ClickType.SINGLE:
                self._execute_with_cursor_restore(background, self._single_click, abs_x, abs_y)
            elif click_type == ClickType.DOUBLE:
                self._execute_with_cursor_restore(background, self._double_click, abs_x, abs_y)
            elif click_type == ClickType.LONG_PRESS:
                self._execute_with_cursor_restore(background, self._long_press, abs_x, abs_y, duration_ms, stop_event)
            return True
        except Exception:
            return False

    def bring_target_to_front(self, window: Optional[WindowInfo] = None) -> bool:
        """Bring the target window to the foreground."""
        if window is None:
            window = self._screen_capture.get_cached_window()
            if window is None:
                window = self._screen_capture.find_iphone_mirroring_window()
        if window is None:
            return False

        return self._screen_capture.bring_window_to_front(window)

    @staticmethod
    def _execute_with_cursor_restore(is_background: bool, click_func, *args, **kwargs):
        """Execute a click function. If is_background is True, it restores cursor position."""
        original_loc = None
        if is_background:
            # Capture the current global mouse location
            evt = CGEventCreate(None)
            original_loc = CGEventGetLocation(evt)

        # Perform the actual click
        click_func(*args, **kwargs)

        if is_background and original_loc is not None:
            # Revert cursor back to original location instantly
            move_event = CGEventCreateMouseEvent(
                None, kCGEventMouseMoved, original_loc, 0
            )
            CGEventPost(kCGHIDEventTap, move_event)

    @staticmethod
    def _single_click(x: int, y: int):
        """Perform a single left click at absolute coordinates."""
        point = CGPointMake(float(x), float(y))

        # Mouse down
        event_down = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDown, point, 0
        )
        CGEventPost(kCGHIDEventTap, event_down)

        time.sleep(0.05)  # Small delay between down/up

        # Mouse up
        event_up = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseUp, point, 0
        )
        CGEventPost(kCGHIDEventTap, event_up)

    @staticmethod
    def _double_click(x: int, y: int):
        """Perform a double click at absolute coordinates."""
        point = CGPointMake(float(x), float(y))

        # First click
        event_down1 = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDown, point, 0
        )
        CGEventSetIntegerValueField(event_down1, kCGMouseEventClickState, 1)
        CGEventPost(kCGHIDEventTap, event_down1)

        event_up1 = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseUp, point, 0
        )
        CGEventSetIntegerValueField(event_up1, kCGMouseEventClickState, 1)
        CGEventPost(kCGHIDEventTap, event_up1)

        time.sleep(0.05)

        # Second click
        event_down2 = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDown, point, 0
        )
        CGEventSetIntegerValueField(event_down2, kCGMouseEventClickState, 2)
        CGEventPost(kCGHIDEventTap, event_down2)

        event_up2 = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseUp, point, 0
        )
        CGEventSetIntegerValueField(event_up2, kCGMouseEventClickState, 2)
        CGEventPost(kCGHIDEventTap, event_up2)

    @staticmethod
    def _long_press(x: int, y: int, duration_ms: int = 500, stop_event=None):
        """Perform a long press at absolute coordinates."""
        point = CGPointMake(float(x), float(y))

        event_down = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDown, point, 0
        )
        CGEventPost(kCGHIDEventTap, event_down)

        # Hold for the specified duration (interruptible if stop_event is provided)
        if stop_event is not None:
            stop_event.wait(duration_ms / 1000.0)
        else:
            time.sleep(duration_ms / 1000.0)

        event_up = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseUp, point, 0
        )
        CGEventPost(kCGHIDEventTap, event_up)
