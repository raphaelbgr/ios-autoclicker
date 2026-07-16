"""
Screen capture module for macOS.
Captures the iPhone Mirroring window content using Quartz APIs.
"""

import threading
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
        """Capture a window and return as numpy array (BGR format for OpenCV).

        Uses ScreenCaptureKit (the sanctioned, sandbox-compatible API and the
        replacement for the deprecated CGWindowListCreateImage). Falls back to
        the legacy path only if ScreenCaptureKit is unavailable or fails, so the
        app never regresses on machines/situations where SCK misbehaves.

        NOTE for the Mac App Store build: drop the legacy fallback (it calls the
        deprecated CGWindowListCreateImage) so the shipped binary is SCK-only.
        """
        try:
            img = self._capture_window_sck(window)
            if img is not None:
                return img
        except Exception as e:
            print(f"[capture_window SCK] falling back (id={window.window_id} "
                  f"owner='{window.owner_name}'): {e}", flush=True)
        return self._capture_window_legacy(window)

    # ── ScreenCaptureKit path (primary) ──

    def _get_shareable_content(self, timeout: float = 5.0):
        """Fetch SCShareableContent synchronously by bridging the async
        completion handler with a timeout-guarded Event (never blocks forever;
        the timeout also avoids the PyObjC teardown SIGTRAP on a lost callback)."""
        from ScreenCaptureKit import SCShareableContent
        holder = {}
        done = threading.Event()

        def handler(content, error):
            holder["content"] = content
            holder["error"] = error
            done.set()

        SCShareableContent.getShareableContentWithCompletionHandler_(handler)
        if not done.wait(timeout):
            return None
        if holder.get("error") is not None:
            return None
        return holder.get("content")

    def _capture_window_sck(self, window: WindowInfo) -> Optional[np.ndarray]:
        """Capture via ScreenCaptureKit's SCScreenshotManager (macOS 14+)."""
        from ScreenCaptureKit import (
            SCContentFilter, SCScreenshotManager, SCStreamConfiguration,
        )

        content = self._get_shareable_content()
        if content is None:
            return None

        # Build a content filter for the target (a single window, or a display
        # for the whole screen).
        if window.is_entire_screen:
            displays = content.displays()
            if not displays:
                return None
            content_filter = SCContentFilter.alloc().initWithDisplay_excludingWindows_(
                displays[0], []
            )
        else:
            target = None
            for w in content.windows():
                if int(w.windowID()) == int(window.window_id):
                    target = w
                    break
            if target is None:
                return None
            content_filter = SCContentFilter.alloc().initWithDesktopIndependentWindow_(
                target
            )

        # Size the output buffer in PIXELS (Retina-aware), matching what the
        # legacy CGWindowListCreateImage produced so stored references still match.
        scale = self._filter_pixel_scale(content_filter)
        cfg = SCStreamConfiguration.alloc().init()
        cfg.setWidth_(max(1, int(round(window.width * scale))))
        cfg.setHeight_(max(1, int(round(window.height * scale))))
        try:
            cfg.setShowsCursor_(False)  # keep the pointer out of reference matches
        except Exception:
            pass

        img_holder = {}
        done = threading.Event()

        def cap_handler(cg_image, error):
            img_holder["image"] = cg_image
            img_holder["error"] = error
            done.set()

        SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            content_filter, cfg, cap_handler
        )
        if not done.wait(5.0):
            return None
        cg_image = img_holder.get("image")
        if cg_image is None or img_holder.get("error") is not None:
            return None
        return self._cgimage_to_numpy(cg_image)

    @staticmethod
    def _filter_pixel_scale(content_filter) -> float:
        """Points→pixels scale for a content filter (2.0 on Retina)."""
        try:
            s = float(content_filter.pointPixelScale())  # SCContentFilter, macOS 14+
            if s > 0:
                return s
        except Exception:
            pass
        try:
            from AppKit import NSScreen
            return float(NSScreen.mainScreen().backingScaleFactor())
        except Exception:
            return 2.0

    # ── Legacy path (fallback; deprecated CGWindowListCreateImage) ──

    def _capture_window_legacy(self, window: WindowInfo) -> Optional[np.ndarray]:
        """Deprecated Quartz capture — fallback only. Remove for a MAS-only build."""
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
