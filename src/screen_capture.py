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

    @property
    def is_entire_screen(self) -> bool:
        return self.owner_name == "[Entire Screen]"


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

    def find_target_window(self, target_name: str) -> Optional[WindowInfo]:
        """Find the window that matches the target name, or 'Entire Screen'."""
        if target_name == "[Entire Screen]":
            # Return a mock WindowInfo for the whole screen
            import Quartz
            main_monitor = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
            w = WindowInfo(
                window_id=0,
                owner_name="[Entire Screen]",
                window_name="Entire Screen",
                bounds={"X": main_monitor.origin.x, "Y": main_monitor.origin.y, "Width": main_monitor.size.width, "Height": main_monitor.size.height},
                owner_pid=0,
                is_on_screen=True
            )
            self._cached_window = w
            return w

        windows = self.list_windows()
        
        # 1. Exact Composite Match (ID::Owner::Name) prioritizing ID for the active session
        parts = target_name.split("::", 2)
        if len(parts) == 3:
            target_id, target_owner, target_wname = parts
            target_id = int(target_id)
            for w in windows:
                if w.window_id == target_id:
                    self._cached_window = w
                    return w
                    
            # Fallback 1a: Match by exact owner + window name
            for w in windows:
                if w.owner_name == target_owner and w.window_name == target_wname:
                    self._cached_window = w
                    return w
                    
            target_name = target_owner # Downgrade to owner matching if strict composite fails

        # First exact owner match
        for w in windows:
            if target_name.lower() == w.owner_name.lower():
                self._cached_window = w
                return w
        # Second substring owner match
        for w in windows:
            if target_name.lower() in w.owner_name.lower():
                self._cached_window = w
                return w
                
        # If looking for iPhone Mirroring specifically, fallbacks
        if target_name == IPHONE_MIRRORING_APP_NAME:
            for w in windows:
                if (IPHONE_MIRRORING_APP_NAME.lower() in w.owner_name.lower() or
                        IPHONE_MIRRORING_BUNDLE_ID.lower() in w.owner_name.lower() or
                        "iphone" in w.owner_name.lower() or "mirror" in w.owner_name.lower()):
                    self._cached_window = w
                    return w
                    
        return None

    def capture_window(self, window: WindowInfo) -> Optional[np.ndarray]:
        """Capture a window and return as numpy array (BGR format for OpenCV)."""
        try:
            from Quartz import CGRectInfinite
            if window.is_entire_screen:
                cg_image = CGWindowListCreateImage(
                    CGRectInfinite,
                    kCGWindowListOptionOnScreenOnly,
                    kCGNullWindowID,
                    kCGWindowImageBoundsIgnoreFraming,
                )
            else:
                cg_image = CGWindowListCreateImage(
                    CGRectNull,
                    kCGWindowListOptionIncludingWindow,
                    window.window_id,
                    kCGWindowImageBoundsIgnoreFraming,
                )
            if cg_image is None:
                return None

            return self._cgimage_to_numpy(cg_image)
        except Exception as e:
            import traceback
            print(f"[capture_window ERROR] id={window.window_id} owner='{window.owner_name}': {e}", flush=True)
            traceback.print_exc()
            return None

    def capture_target(self, target_name: str) -> Optional[np.ndarray]:
        """Convenience: find and capture the target window."""
        window = self.find_target_window(target_name)
        if window is None:
            return None
        return self.capture_window(window)

    def get_cached_window(self) -> Optional[WindowInfo]:
        """Return the last found target window info."""
        return self._cached_window

    @staticmethod
    def bring_window_to_front(window: WindowInfo) -> bool:
        """Bring a window's application to the foreground.
        Must be called from the main thread (AppKit requirement)."""
        if window.is_entire_screen:
            return True
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
