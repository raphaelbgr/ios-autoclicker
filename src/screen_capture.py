"""
Screen capture module for macOS.
Captures the iPhone Mirroring window content using Quartz APIs.
"""

import numpy as np
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass

import Quartz
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGNullWindowID,
    CGWindowListCreateImage,
    CGRectNull,
    kCGWindowListOptionIncludingWindow,
    kCGWindowImageBoundsIgnoreFraming,
    CGImageGetWidth,
    CGImageGetHeight,
    CGImageGetBytesPerRow,
    CGImageGetDataProvider,
    CGDataProviderCopyData,
)
from AppKit import NSWorkspace, NSRunningApplication
import CoreFoundation


IPHONE_MIRRORING_BUNDLE_ID = "com.apple.ScreenContinuity"
IPHONE_MIRRORING_APP_NAME = "iPhone Mirroring"


@dataclass
class WindowInfo:
    """Represents a macOS window."""
    window_id: int
    owner_name: str
    window_name: str
    bounds: Dict  # {X, Y, Width, Height}
    owner_pid: int
    is_on_screen: bool

    @property
    def width(self) -> int:
        return int(self.bounds.get("Width", 0))

    @property
    def height(self) -> int:
        return int(self.bounds.get("Height", 0))

    @property
    def x(self) -> int:
        return int(self.bounds.get("X", 0))

    @property
    def y(self) -> int:
        return int(self.bounds.get("Y", 0))


class ScreenCapture:
    """Captures screenshots of specific macOS windows."""

    def __init__(self):
        self._cached_window: Optional[WindowInfo] = None

    def list_windows(self) -> List[WindowInfo]:
        """List all visible windows on screen."""
        window_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        )
        windows = []
        if window_list is None:
            return windows

        for window in window_list:
            owner_name = window.get("kCGWindowOwnerName", "")
            window_name = window.get("kCGWindowName", "")
            bounds = window.get("kCGWindowBounds", {})
            window_id = window.get("kCGWindowNumber", 0)
            owner_pid = window.get("kCGWindowOwnerPID", 0)
            layer = window.get("kCGWindowLayer", 0)

            # Skip system UI elements (menu bar, dock, etc.)
            if layer != 0:
                continue

            # Skip windows with no size
            w = bounds.get("Width", 0)
            h = bounds.get("Height", 0)
            if w <= 1 or h <= 1:
                continue

            windows.append(WindowInfo(
                window_id=window_id,
                owner_name=owner_name,
                window_name=window_name,
                bounds=dict(bounds),
                owner_pid=owner_pid,
                is_on_screen=True,
            ))

        return windows

    def find_iphone_mirroring_window(self) -> Optional[WindowInfo]:
        """Find the iPhone Mirroring window."""
        windows = self.list_windows()
        for w in windows:
            if (IPHONE_MIRRORING_APP_NAME.lower() in w.owner_name.lower() or
                    IPHONE_MIRRORING_BUNDLE_ID.lower() in w.owner_name.lower()):
                self._cached_window = w
                return w
        # Fallback: search all windows
        for w in windows:
            if "iphone" in w.owner_name.lower() or "mirror" in w.owner_name.lower():
                self._cached_window = w
                return w
        return None

    def capture_window(self, window: WindowInfo) -> Optional[np.ndarray]:
        """Capture a window and return as numpy array (BGR format for OpenCV)."""
        try:
            cg_image = CGWindowListCreateImage(
                CGRectNull,
                kCGWindowListOptionIncludingWindow,
                window.window_id,
                kCGWindowImageBoundsIgnoreFraming,
            )
            if cg_image is None:
                return None

            return self._cgimage_to_numpy(cg_image)
        except Exception:
            return None

    def capture_iphone_mirroring(self) -> Optional[np.ndarray]:
        """Convenience: find and capture the iPhone Mirroring window."""
        window = self.find_iphone_mirroring_window()
        if window is None:
            return None
        return self.capture_window(window)

    def get_cached_window(self) -> Optional[WindowInfo]:
        """Return the last found iPhone Mirroring window info."""
        return self._cached_window

    @staticmethod
    def bring_window_to_front(window: WindowInfo) -> bool:
        """Bring a window's application to the foreground.
        Must be called from the main thread (AppKit requirement)."""
        try:
            workspace = NSWorkspace.sharedWorkspace()
            apps = workspace.runningApplications()
            for app in apps:
                if app.processIdentifier() == window.owner_pid:
                    # Try modern API first (macOS 14+), then legacy
                    try:
                        app.activate()
                    except (TypeError, AttributeError):
                        try:
                            app.activateWithOptions_(1 << 1)  # NSApplicationActivateIgnoringOtherApps
                        except Exception:
                            pass
                    return True
            return False
        except Exception:
            # Fallback: use AppleScript
            try:
                import subprocess
                owner = window.owner_name
                subprocess.run(
                    ["osascript", "-e", f'tell application "{owner}" to activate'],
                    capture_output=True, timeout=3
                )
                return True
            except Exception:
                return False

    @staticmethod
    def _cgimage_to_numpy(cg_image) -> np.ndarray:
        """Convert a CGImage to a numpy array in BGR format (OpenCV compatible)."""
        width = CGImageGetWidth(cg_image)
        height = CGImageGetHeight(cg_image)
        bytes_per_row = CGImageGetBytesPerRow(cg_image)

        data_provider = CGImageGetDataProvider(cg_image)
        data = CGDataProviderCopyData(data_provider)
        raw = np.frombuffer(data, dtype=np.uint8)

        # CGImage provides data as BGRA (on macOS)
        img = raw.reshape((height, bytes_per_row // 4, 4))
        img = img[:, :width, :]  # Trim padding

        # Convert BGRA to BGR for OpenCV
        bgr = img[:, :, :3]
        return bgr.copy()

    @staticmethod
    def check_screen_recording_permission() -> bool:
        """Check if the app has screen recording permission by trying to capture."""
        try:
            window_list = CGWindowListCopyWindowInfo(
                kCGWindowListOptionOnScreenOnly, kCGNullWindowID
            )
            if window_list is None:
                return False
            # Try to capture a window to verify
            for window in window_list:
                wid = window.get("kCGWindowNumber", 0)
                if wid > 0:
                    img = CGWindowListCreateImage(
                        CGRectNull,
                        kCGWindowListOptionIncludingWindow,
                        wid,
                        kCGWindowImageBoundsIgnoreFraming,
                    )
                    return img is not None
            return False
        except Exception:
            return False
