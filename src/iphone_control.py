"""
iPhone Mirroring control via macOS AppleScript / Accessibility.

Drives the mirrored iPhone through iPhone Mirroring's own View-menu commands
(verified present in the app's menu bar):
    Home Screen   = ⌘1
    App Switcher  = ⌘2
    Spotlight     = ⌘3
Clicking the menu item via System Events is position-independent (no reliance
on coordinates or which app is frontmost beyond activating it first).
"""

import subprocess

DEFAULT_PROCESS = "iPhone Mirroring"

# command key -> exact View-menu item name (verified from the live menu bar)
_MENU_ITEMS = {
    "home": "Home Screen",
    "app_switcher": "App Switcher",
    "spotlight": "Spotlight",
}


def _run(script: str, timeout: float = 5.0) -> bool:
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0
    except Exception:
        return False


def activate(process_name: str = DEFAULT_PROCESS) -> bool:
    """Bring iPhone Mirroring to the front (required before sending menu/keys)."""
    return _run(f'tell application "{process_name}" to activate')


def send_command(command: str, process_name: str = DEFAULT_PROCESS) -> bool:
    """Trigger a View-menu command: 'home', 'app_switcher', or 'spotlight'."""
    item = _MENU_ITEMS.get(command)
    if not item:
        return False
    activate(process_name)
    script = (
        f'tell application "System Events" to tell process "{process_name}" '
        f'to click menu item "{item}" of menu 1 of menu bar item "View" of menu bar 1'
    )
    return _run(script)


def type_text(text: str, press_return: bool = True,
              process_name: str = DEFAULT_PROCESS) -> bool:
    """Type text into the (already-activated) iPhone Mirroring window, optionally
    pressing Return. Used to launch an app via Spotlight."""
    activate(process_name)
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    lines = ['tell application "System Events"', f'keystroke "{safe}"']
    if press_return:
        lines.append("key code 36")  # Return
    lines.append("end tell")
    return _run("\n".join(lines))
