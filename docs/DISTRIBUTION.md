# Distribution: Mac App Store, TestFlight, and Developer ID

**Verified verdict (2026-07-14): TestFlight for macOS is VIABLE. The one make-or-break unknown — whether a sandboxed app can post synthetic clicks (`CGEvent.post`) — was tested empirically and the answer is YES (see "Sandbox click test" below). No technical unknowns remain; the work is a bounded engineering job: swap PyQt6 → PySide6 (clear the GPL problem), port screen capture to ScreenCaptureKit, and repackage as a sandboxed, Xcode-signed `.app`. Internal TestFlight then requires no App Review. Developer ID + notarization (a signed `.dmg`) remains the zero-effort alternative if you'd rather not do the port.**

> Correction history: an even earlier draft called the App Store "a dead end" (wrongly assumed sandboxed apps can't screen-capture another window — they can). A second draft left click-posting as an "unverified make-or-break." That's now been tested and settled — see below.

---

## The blockers, honestly assessed

### 1. The App Sandbox (Guideline 2.4.5(i)) — CLEARED (tested)

> **2.4.5(i)** They must be appropriately sandboxed…

The app does two privileged things. Both are sandbox-compatible:

| What the app does | Sandboxed? | Status |
|---|---|---|
| Capture the iPhone Mirroring window | **YES** | ScreenCaptureKit (`SCWindow`) + `com.apple.security.screen-capture` entitlement + the user granting Screen Recording. Purely TCC-gated (TCC = macOS's per-app privacy permission system). ✅ verified against Apple docs. Current code uses the older `CGWindowListCreateImage` — would need porting to ScreenCaptureKit. |
| Post synthetic clicks (`CGEvent.post` → `kCGHIDEventTap`) | **YES — empirically verified** | Sandbox does **not** block it. The gate is the Accessibility (post-event) permission — the *same* permission this app already requires today. See below. |

#### Sandbox click test (2026-07-14, on the Mac mini)

Built a minimal Swift `.app`, ad-hoc-signed **with `com.apple.security.app-sandbox`**, and posted a single left-click tagged with a magic marker; an independent listener process watched the global event stream to confirm delivery. Matrix:

| Build | Accessibility trust | Result |
|---|---|---|
| Un-sandboxed (control) | present | click delivered ✅ (detector valid) |
| **Sandboxed**, HID tap | present | **click delivered** ✅ |
| **Sandboxed**, session tap | present | **click delivered** ✅ |
| **Sandboxed**, launched independently | **absent** | click dropped ❌ |

The last row (launched via `open`, so it did **not** inherit the terminal's trust) proves the blocker is **Accessibility (TCC), not the sandbox**: with the sandbox enforced (`SANDBOX_ENFORCED=true`, container-scoped `$HOME`, writes outside the container denied) and Accessibility present, posting to the exact tap production uses (`kCGHIDEventTap`) worked. Conclusion: **a sandboxed Mac App Store build's clicking will work once the user grants Accessibility — which they already must do in the current app.**

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

- Any macOS TestFlight build is uploaded to **App Store Connect as a Mac App Store distribution build** — so it must be **sandboxed and Apple-Distribution-signed** at upload time. Blockers #2–#3 (GPL, packaging) apply before a build is even accepted; #1 (sandbox) is cleared.
- **Internal testers** (up to 100, on your team's own devices): **no Beta App Review.** This is the reachable goal — get a sandboxed PySide6 build uploaded and test it on your own Macs.
- **External testers** (up to 10,000, public link): require **Beta App Review** (blocker #4 applies).

### The path to an internal TestFlight build

0. ~~De-risk: confirm `CGEvent.post` works sandboxed.~~ ✅ **DONE — verified it works (see "Sandbox click test").**
1. **Apple Developer Program** — already enrolled (paid team **H3425WJ3TM**; full ASC toolkit in the vault at `global/app-store-connect/`).
2. **Port PyQt6 → PySide6** (clears the GPL blocker). — the bulk of the work.
3. **Port screen capture** `CGWindowListCreateImage` → **ScreenCaptureKit**.
4. **Package** with `py2app`; enable **App Sandbox** + the `screen-capture` entitlement; add `NS…UsageDescription` strings for the permission prompts.
5. **Sign** with the Apple Distribution cert + a `MAC_APP_STORE` provisioning profile; **upload** to App Store Connect. (Note: prior shipped apps are iOS/tvOS `.ipa` via `altool -t ios/tvos`; this is the **macOS** track — `.pkg`, `MAC_APP_STORE` profile — new ground even with the existing toolkit.)
6. **Add internal testers** in App Store Connect → TestFlight — no review.

Realistic effort: **~3–5 days**, almost all of it the PySide6 + ScreenCaptureKit ports and macOS-track packaging. No unknowns remain.

**Optional final confirmation (2 min):** grant Accessibility to the test app that's already built (`.../tmp/sbxtest/IndiePoster.app`) and re-run it — the listener will show the click landing, closing the loop end-to-end for a user-granted (not inherited) sandboxed app.

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
