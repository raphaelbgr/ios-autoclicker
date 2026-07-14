# Timeline Format

A timeline is a list of **actions**. Each action waits for a screen state (a reference screenshot, on-screen text, or another action firing), then performs a click or an app-lifecycle operation.

There are two on-disk formats.

## 1. `.zip` package — self-contained (recommended for sharing)

**Use this to share a timeline or move it between machines.** Produced by **📤 Export**; consumed by **📥 Import**.

```
My Automation.zip
├── timeline.json                     # paths rewritten to archive-relative
└── screenshots/
    ├── action_0_1773820867625_1.png
    ├── action_1_1773814763058_2.png
    └── …
```

Inside the package, every `screenshot_path` is **archive-relative** (`screenshots/<name>.png`), never an absolute path — that is what makes the package portable.

On import, the bundled screenshots are extracted into the **current project's** `screenshots/` folder and each action's `screenshot_path` is rewritten to point there. Extraction is by basename, so a crafted archive cannot write outside the project's screenshots directory.

Behaviour worth knowing:
- **Shared screenshots are deduped** — two actions referencing the same file bundle it once.
- **Missing screenshots are skipped** — the action is still exported, keeping its original path, so a same-machine import still resolves it.
- **Actions with no screenshot** (text-only or `after_trigger` actions) round-trip unchanged.

## 2. `.json` — timeline only (legacy)

Still supported for both export (pick *JSON only* in the save dialog) and import.

⚠️ **A `.json` export is not portable.** It stores `screenshot_path` as an **absolute** path on the exporting machine. Open it anywhere else — or after deleting the source project — and every action loses its trigger screenshot, so recognition silently stops working. Use the `.zip` package unless you have a specific reason not to.

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
      "screenshot_path": "projects/default/screenshots/action_0_123456_1.png",
      "match_texts": "PLAY, START"
    }
  ]
}
```

## Action fields

| Field | Type | Default | Meaning |
|---|---|---|---|
| `delay_ms` | int | — | Wait this long **after** the trigger matches, before acting |
| `x`, `y` | int | — | Click position, **relative to the target window** |
| `click_type` | str | `single` | `single` · `double` · `long_press` |
| `duration_ms` | int | `100` | Hold time for `long_press` (ms → hours) |
| `label` | str | `""` | Your name for the action |
| `threshold` | float | `0.85` | Per-action SSIM similarity required to fire (0.0–1.0) |
| `screenshot_path` | str | `""` | Reference screenshot that triggers this action |
| `match_texts` | str | `""` | Comma-separated OCR patterns, **OR** logic (`"game over, defeat"`) |
| `enabled` | bool | `true` | Unchecked actions are skipped |
| `repeat_count` | int | `1` | Fire N clicks per match (spaced within a 1 s window) |

### App-lifecycle fields
Only written when `action_type != "click"`, so plain click entries stay clean.

| Field | Default | Meaning |
|---|---|---|
| `action_type` | `click` | `click` · `close_app` · `open_app` |
| `close_method` | `force_quit` | `force_quit` (App Switcher swipe) · `home` |
| `open_method` | `spotlight` | `spotlight` (type the name) · `tap_icon` (click x,y) |
| `app_name` | `""` | App to type into Spotlight for `open_app` |
| `post_delay_ms` | `0` | Wait after the app action completes |

### Trigger fields
Only written when `trigger_type != "recognition"`.

| Field | Default | Meaning |
|---|---|---|
| `trigger_type` | `recognition` | `recognition` (screenshot/OCR) · `after_trigger` (fires a set time after another action) |
| `after_index` | `1` | 1-based number of the action this one follows |

## Backward compatibility

Old files that used `timestamp_ms` instead of `delay_ms` still load — `ClickAction.from_dict` accepts either. Every field is optional on load and falls back to the default above, so timelines from earlier versions import without edits.
