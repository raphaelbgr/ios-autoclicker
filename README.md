# 🎯 iOS Auto-Clicker for macOS

A macOS desktop application that automates taps on your iPhone through the **iPhone Mirroring** window. It uses **screen recognition** to detect specific screen states, then executes click actions automatically — no jailbreak required.

![macOS](https://img.shields.io/badge/macOS-15.0+-black?logo=apple)
![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)

## How It Works

The app watches the iPhone Mirroring window on your Mac and compares it against reference screenshots you provide. When the screen matches a known state, it automatically clicks at the position you defined.

```
┌─────────────────────────────────────────────────────────┐
│                    Main Loop                            │
│                                                         │
│   1. Capture iPhone Mirroring window (every ~500ms)     │
│   2. Compare against ALL action screenshots (SSIM)      │
│   3. If no screenshot match → try OCR text matching     │
│   4. Best match found → wait delay → click → cooldown   │
│   5. No match → keep scanning                           │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Screen Matching

Each click action has its **own reference screenshot** and **similarity threshold**. The app uses **SSIM (Structural Similarity Index)** to compare the current screen against each action's screenshot. This means:

- **No training needed** — just take a screenshot of the screen state you want to detect
- **Threshold control** — set how closely the screen must match (default 85%)
- **Per-action thresholds** — dynamic screens (like games) can use a lower threshold (e.g., 60-75%) while static menus keep 85%+

### Text Matching (OCR)

Actions can optionally include **text patterns** for matching. The app uses the native **macOS Vision framework** for text recognition — no external APIs or dependencies needed. Text patterns use comma-separated OR logic:

```
"game over, victory, score"  →  matches if ANY of these appear on screen
```

### Click Execution

When a match is found:
1. **Wait** the configured delay (gives the screen time to fully load)
2. **Bring** the iPhone Mirroring window to the foreground
3. **Click** at the stored (x, y) coordinates using macOS CGEvent API
4. **Cooldown** for 1 second (screen will change after clicking)

Supported click types: **Single Click**, **Double Click**, **Long Press** (configurable hold duration).

## Features

- 📸 **Per-action screenshots** — each click action has its own trigger screenshot
- 🎯 **Visual click position picker** — click on the screenshot to set coordinates
- 📊 **Real-time Match Progress** — Every action displays a live, animated progress bar showing its similarity to the current screen
- 👻 **Ghost Click (Background mode)** — Execute clicks instantly without visibly moving your mouse or stealing focus
- 📝 **OCR text matching** — fallback detection using on-screen text
- ⏯️ **Action Toggles** — Easily disable/enable specific actions in your timeline without deleting them
- 🔁 **Repeat Clicks** — Issue rapid-fire multi-clicks per single trigger match (great for games)
- ⏱️ **Infinite Long Presses** — Hold specific clicks for milliseconds to hours, safely interruptible
- 🔄 **Loop support** — repeat the sequence N times or infinitely
- 💾 **Auto-save** — all project data persists automatically between sessions
- 📤 **Import/Export** — save and share timelines as JSON files
- 📋 **Activity log** — color-coded real-time log of all events
- 🎨 **Dark theme** — polished, modern UI

## Requirements

- **macOS 15.0+** (Sequoia) with iPhone Mirroring
- **Python 3.11+**
- **iPhone** paired for iPhone Mirroring

### macOS Permissions

The app needs two permissions (it will guide you on first launch):

| Permission | Where to Enable | Why |
|---|---|---|
| **Screen Recording** | System Settings → Privacy & Security → Screen Recording | Capture the iPhone Mirroring window content |
| **Accessibility** | System Settings → Privacy & Security → Accessibility | Send click events to the window |

> Add your **Terminal app** (or iTerm, etc.) to both permission lists.

## Installation

```bash
git clone https://github.com/raphaelbgr/ios-autoclicker.git
cd ios-autoclicker
./run.sh
```

That's it. The `run.sh` script automatically:
1. Creates a Python virtual environment
2. Installs all dependencies
3. Launches the app

### macOS Desktop App Shortcut
A native `.app` bundle named **`iOS AutoClicker.app`** with a custom icon is included in the project folder. You can double-click this app or use the provided alias on your Desktop to launch the Auto-Clicker without opening the terminal. Note: Be sure to grant this app Accessibility permissions on its first run if prompted.

### Manual Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Usage

### 1. Open iPhone Mirroring

Open the **iPhone Mirroring** app on your Mac. The auto-clicker will detect it automatically.

### 2. Create Click Actions

Click **➕ Add** to create a new action:

1. **Capture a screenshot** — click "📸 Capture Now" to take a snapshot of the current iPhone screen
2. **Pick click position** — click on the screenshot where you want the tap to happen
3. **Set match threshold** — how closely the screen must match (85% is good for static screens, lower for dynamic ones)
4. **Set delay** — how long to wait after matching before clicking (in ms)
5. **Add text patterns** (optional) — comma-separated text to match via OCR

### 3. Build Your Sequence

Add multiple actions for different screen states. For example, a game automation might look like:

| # | Screenshot | Action | Threshold |
|---|---|---|---|
| 1 | Main menu | Tap "Play" | 85% |
| 2 | Level select | Tap level | 85% |
| 3 | Game over screen | Tap "Collect" | 65% |
| 4 | Results screen | Tap "Continue" | 85% |
| 5 | High scores | Tap "OK" | 85% |

### 4. Start Automation

Click **▶ Start Automation**. The app will:
- Continuously capture the iPhone Mirroring window
- Compare against ALL action screenshots simultaneously
- Click the best matching action
- Log everything in the activity log

### 5. Stop

Click **⏹ Stop** or close the app. Your actions are auto-saved.

## Architecture

```
src/
├── main.py                  # Entry point, permission checks
├── screen_capture.py        # Quartz API window capture
├── screen_recognizer.py     # SSIM + template matching
├── click_engine.py          # CGEvent click delivery
├── timeline.py              # Click action data model + serialization
├── ocr.py                   # macOS Vision framework OCR
├── project.py               # Auto-save/load project data
├── logger.py                # Timestamped activity logging
└── gui/
    ├── main_window.py       # Main window + automation loop
    ├── timeline_editor.py   # Add/edit click action dialog
    ├── click_position_picker.py  # Click-on-image coordinate picker
    ├── screen_setup.py      # Window detection panel
    ├── log_viewer.py        # Color-coded log display
    └── styles.py            # Dark theme stylesheet
```

### Key Technologies

| Component | Technology | Why |
|---|---|---|
| GUI | PyQt6 | Cross-platform, polished native feel |
| Screen Recognition | OpenCV + SSIM (scikit-image) | Fast, no training needed |
| OCR | macOS Vision framework (PyObjC) | Native, no external APIs |
| Click Delivery | CGEvent (Quartz) | Standard macOS programmatic clicks |
| Window Capture | CGWindowListCreateImage (Quartz) | Low-level, reliable screen capture |

## Timeline JSON Format

Timelines are saved as JSON and can be shared:

```json
{
  "name": "My Automation",
  "loop": true,
  "loop_count": 0,
  "actions": [
    {
      "delay_ms": 1000,
      "x": 181,
      "y": 696,
      "click_type": "single",
      "duration_ms": 500,
      "repeat_count": 1,
      "label": "Tap Play Button",
      "threshold": 0.85,
      "enabled": true,
      "screenshot_path": "projects/default/screenshots/action_0_123456.png",
      "match_texts": "PLAY, START"
    }
  ]
}
```

## Troubleshooting

| Problem | Solution |
|---|---|
| "No window detected" | Open the iPhone Mirroring app, then click 🔍 Detect |
| Clicks don't register | Enable Accessibility permission for your terminal |
| Black/empty capture | Enable Screen Recording permission for your terminal |
| Low match percentage | Lower the threshold or recapture the screenshot |
| OCR not working | `pyobjc-framework-Vision` should be installed automatically via `run.sh` |

## License

MIT
