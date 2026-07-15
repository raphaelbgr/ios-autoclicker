# Distribution: Mac App Store, TestFlight, and Developer ID

**Corrected verdict (2026-07-14): TestFlight for macOS is *possible*, but NOT with the current build. It requires two changes we control (swap PyQt6 → PySide6 to clear the GPL problem; rebuild as a sandboxed, Xcode-signed `.app`) and hinges on ONE unverified technical fact: whether a sandboxed app can *post* synthetic clicks (`CGEvent.post`). Screen capture in a sandbox is confirmed fine. If click-posting also works sandboxed, TestFlight is a real path. If not, only Developer ID + notarization (a signed `.dmg`) can ship it.**

> This replaces an earlier draft of this doc that said the App Store was "a dead end." That was too strong: I had wrongly assumed a sandboxed app can't screen-capture another window. It can. See the corrections below.

---

## The blockers, honestly assessed

### 1. The App Sandbox (Guideline 2.4.5(i)) — partly clears, one unknown

> **2.4.5(i)** They must be appropriately sandboxed…

The app does two privileged things. Their sandbox status is **not** the same:

| What the app does | Sandboxed? | Status |
|---|---|---|
| Capture the iPhone Mirroring window | **YES — works** | ScreenCaptureKit (`SCWindow`) + `com.apple.security.screen-capture` entitlement + the user granting Screen Recording. Purely TCC-gated (TCC = macOS's per-app privacy permission system). ✅ verified against Apple docs. Current code uses the older `CGWindowListCreateImage` — would need porting to ScreenCaptureKit. |
| Post synthetic clicks (`CGEvent.post`) | **UNKNOWN** | Apple's DTS engineer (Quinn) confirmed sandboxed apps can *listen* to events via a CGEventTap (Input Monitoring). He did **not** confirm *posting*. My sources conflict and no primary source settles it. **This is the single make-or-break fact and it is unverified.** |

So the sandbox is not the flat wall I described before. Screen capture is fine; the whole thing rides on whether `CGEvent.post` (a global click at coordinates, after we bring the target window frontmost — not AppleScript-style control of another app) is permitted from inside the sandbox. **This must be tested empirically before committing to the TestFlight path.**

### 2. GPL-3.0 licensing conflict — real, but solvable

**PyQt6 is `GPL-3.0-only`** (verified: `pip show PyQt6` → `License-Expression: GPL-3.0-only`; Riverbank offers no LGPL option). GPLv3 is incompatible with the App Store's terms (its DRM/per-device restrictions violate GPL's "no further restrictions" — the reason VLC was pulled).

**Fix:** port the GUI from PyQt6 to **PySide6** — Qt's *official* binding, licensed LGPL, which App Store distribution allows. The two APIs are ~95% identical; this is a mechanical port, not a rewrite. (Alternative: buy a commercial PyQt license from Riverbank — costs money, no code change.)

### 3. Packaging (Guideline 2.4.5(ii)) — must rebuild the bundle

The current `.app` is a shell script launching a hand-made venv. A Mac App Store build must be a self-contained, Xcode-signed bundle. **Fix:** package with `py2app` into a real `.app` embedding the Python runtime, then sign with an Apple Distribution certificate + a Mac App Store provisioning profile carrying the sandbox entitlement. (A bundled Python interpreter is allowed — many shipping MAS apps embed one; it is not the "deprecated tech" 2.4.5(viii) targets.)

### 4. Purpose / "game bot" (Guideline 2.5.1) — review risk, not an upload blocker

Automating gameplay isn't the "intended purpose" of Accessibility/event APIs, and the automated games' own ToS may forbid it. This only matters for **External** TestFlight testers and the final App Store release (both need Beta/App Review). **Internal** TestFlight testing (your own devices) skips review entirely — so you can dogfood on TestFlight even if this would block a public release.

---

## TestFlight for macOS — how it actually works

TestFlight supports macOS (since 2021, Xcode 13+). Key facts for this app:

- Any macOS TestFlight build is uploaded to **App Store Connect as a Mac App Store distribution build** — so it must be **sandboxed and Apple-Distribution-signed** at upload time. Blockers #1–#3 all apply before a build is even accepted.
- **Internal testers** (up to 100, on your team's own devices): **no Beta App Review.** This is the reachable goal — get a sandboxed PySide6 build uploaded and test it on your own Macs.
- **External testers** (up to 10,000, public link): require **Beta App Review** (blocker #4 applies).

### The path to an internal TestFlight build

0. **De-risk first (do this before anything else):** build a throwaway sandboxed binary that calls `CGEvent.post` and confirm a click actually lands in another app after granting Accessibility. If it fails, stop — TestFlight is impossible and Developer ID is the only route.
1. **Enrol in the Apple Developer Program** ($99/yr); note your **Team ID**.
2. **Port PyQt6 → PySide6** (clears the GPL blocker).
3. **Port screen capture** `CGWindowListCreateImage` → **ScreenCaptureKit**.
4. **Package** with `py2app`; enable **App Sandbox** + the `screen-capture` entitlement; add `NS…UsageDescription` strings for the permission prompts.
5. **Sign** with Apple Distribution cert + Mac App Store provisioning profile; **upload** to App Store Connect via Xcode Organizer or Transporter.
6. **Add internal testers** in App Store Connect → TestFlight. They install the TestFlight app and get the build — no review.

Realistic effort: **~3–5 days** (PySide6 port + ScreenCaptureKit port + sandbox signing), gated on step 0 passing.

---

## What to do instead: Developer ID + notarization ✅

This is the correct and fully supported distribution channel for a macOS automation tool. It is what apps like Keyboard Maestro, BetterTouchTool, and Hammerspoon do.

| | Mac App Store / TestFlight | **Developer ID (recommended)** |
|---|---|---|
| Sandbox required | **Yes** — kills the app | **No** |
| Screen Recording + Accessibility | Blocked / contested | **Fully supported** (user grants at first launch) |
| App Review | Yes | **None** |
| GPLv3 (PyQt6) | **License violation** | **Fine** — ship the source, satisfy the GPL |
| Python/PyQt packaging | Rejected | **Fine** |
| Cost | $99/yr Apple Developer Program | $99/yr Apple Developer Program |
| Auto-updates | App Store only | Sparkle, or a GitHub release feed |

### The path

1. **Enrol in the Apple Developer Program** ($99/yr) and create a **Developer ID Application** certificate.
2. **Bundle the app** with `py2app` (or PyInstaller) into a real `.app` — this replaces the current shell-script `.app` wrapper with a self-contained bundle including the Python runtime.
3. **Enable the Hardened Runtime** (required for notarization), with the exceptions Python needs:
   - `com.apple.security.cs.allow-jit`
   - `com.apple.security.cs.allow-unsigned-executable-memory`
   - `com.apple.security.cs.disable-library-validation` (Python loads unsigned `.so` extension modules)
4. **Declare the usage strings** in `Info.plist` so macOS shows a proper permission prompt rather than a silent denial.
5. **Sign** every nested binary (`--deep` is deprecated; sign inner `.so`/`.dylib` files first, then the bundle), then **notarize**:
   ```bash
   xcrun notarytool submit iOS-AutoClicker.dmg \
     --apple-id <you@example.com> --team-id <TEAMID> --password <app-specific-password> \
     --wait
   xcrun stapler staple iOS-AutoClicker.dmg
   ```
6. **Distribute** the stapled `.dmg` as a GitHub release. Gatekeeper opens it with no warning.

Realistic effort: **~1 day**, most of it fighting code-signing of the bundled Python `.so` files.

### Developer ID vs. TestFlight — which to pick

- **Want the fastest working distribution with zero risk?** Developer ID (above). No port, no sandbox, ships this week.
- **Set on TestFlight / eventual Mac App Store?** Do step 0 of the TestFlight path first (prove `CGEvent.post` works sandboxed). If it passes, the PySide6 + ScreenCaptureKit + sandbox work is worth it. If it fails, Developer ID is the only option and TestFlight is genuinely impossible — not a matter of effort.

The two aren't mutually exclusive: you can ship Developer ID now and pursue TestFlight in parallel.

---

## Sources

- [App Review Guidelines — 2.4.5, 2.5.1, 2.5.2](https://developer.apple.com/app-store/review/guidelines/)
- [TestFlight overview — App Store Connect Help](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/)
- [TestFlight, Provisioning Profiles, and the Mac App Store — Apple Developer Forums](https://developer.apple.com/forums/thread/733942)
- [Accessibility permission in sandboxed app — Apple Developer Forums](https://developer.apple.com/forums/thread/707680)
- [Configuring the macOS App Sandbox](https://developer.apple.com/documentation/xcode/configuring-the-macos-app-sandbox)
- [Signing Mac Software with Developer ID](https://developer.apple.com/developer-id/)
- [Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [PyQt6 on PyPI (GPL-3.0-only)](https://pypi.org/project/PyQt6/) · [Riverbank License FAQ](https://riverbankcomputing.com/commercial/license-faq)
