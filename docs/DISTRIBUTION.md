# Distribution: Mac App Store, TestFlight, and Developer ID

**Short version: this app cannot ship on the Mac App Store, and therefore cannot ship via TestFlight either. Distribute it with Developer ID + notarization instead (a signed `.dmg` / GitHub release). That path supports every permission the app needs, has no review, and is the standard route for automation tools on macOS.**

---

## Why the Mac App Store is a dead end

Four independent blockers. Any one of them alone is fatal; all four apply.

### 1. The App Sandbox (App Review Guideline 2.4.5(i))

> **2.4.5** Apps distributed via the Mac App Store have some additional requirements…
> **(i)** They must be appropriately sandboxed…

This app exists to do the two things the sandbox is designed to prevent:

| What the app does | Sandbox reality |
|---|---|
| Captures another app's window (`CGWindowListCreateImage` on iPhone Mirroring) | Requires Screen Recording (`kTCCServiceScreenCapture`) against a process the app doesn't own |
| Posts synthetic clicks into another app (`CGEvent.post`) | Requires event-posting privilege (`kTCCServicePostEvent`) — Apple's own documentation states sandboxed apps "cannot control other apps" |

Apple engineers have noted on the developer forums that `CGEvent.post` uses a privilege that is *technically* compatible with the sandbox — but that nuance doesn't rescue the app, because the whole point of the product is driving a foreign application, which is exactly what 2.4.5(i) and the sandbox exist to stop.

### 2. GPL-3.0 licensing conflict (the hard blocker)

The GUI is built on **PyQt6, which is `GPL-3.0-only`** (verified: `pip show PyQt6` → `License-Expression: GPL-3.0-only`; Riverbank offers no LGPL option — the only alternative is a paid commercial license).

GPLv3 is **incompatible with the App Store's terms of service**. The App Store imposes DRM and per-device usage restrictions that GPLv3 forbids ("no further restrictions"), which is precisely why VLC was pulled from the App Store. Shipping a GPLv3-linked binary through the Mac App Store is a license violation, not merely a review risk.

**To even attempt the store you would have to either** buy a commercial PyQt license from Riverbank, **or** port the GUI to PySide6 (LGPL, Qt's official binding — a real but bounded rewrite).

### 3. Packaging (Guideline 2.4.5(ii) and 2.4.5(viii))

> **(ii)** They must be packaged and submitted using technologies provided in Xcode; no third-party installers allowed. They must also be self-contained, single app installation bundles…
> **(viii)** Apps should run on the currently shipping OS and may not use deprecated or optionally installed technologies (e.g. Java)

This is a Python app with a bundled interpreter and a venv, packaged by hand — not an Xcode-built bundle. A `py2app`/PyInstaller bundle is a third-party packaging technology, and a bundled Python runtime falls in the same category of concern as the explicitly-named Java.

### 4. Purpose (Guideline 2.5.1) and the "it's a game bot" problem

> **2.5.1** Apps may only use public APIs… Apps should use APIs and frameworks **for their intended purposes**…

Using Accessibility/event-posting privileges to automate a game is not the intended purpose of those APIs, and reviewers have historically rejected apps for using Accessibility features for non-accessibility purposes. On top of that, an app whose showcase use case is automating gameplay on a mirrored iPhone likely violates the automated games' own terms of service — an easy rejection on its own.

---

## Why TestFlight doesn't get you around it

TestFlight **does** support macOS apps (since 2021, Xcode 13+, up to 10,000 external testers). But it is **not a side door around App Review**:

- A macOS TestFlight build must be uploaded to App Store Connect as a **Mac App Store distribution build** — signed with a Mac App Store provisioning profile, which means it must carry the **sandbox entitlement**. Blocker #1 applies at *upload* time, before any human sees it.
- **External testers** (anyone outside your team) require the build to pass **Beta App Review**, which applies the same App Review Guidelines quoted above.
- Internal testers (up to 100 people on your own team) skip Beta App Review — but the build still has to be a valid, sandboxed, App-Store-signed bundle to be accepted at all.

So TestFlight is the *same gate*, just earlier. It cannot ship this app.

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

### If you truly want the Mac App Store

You would have to build a **fundamentally different product**: rewrite the GUI in Swift/SwiftUI (dropping PyQt entirely to escape the GPL), sandbox it, and drop the "drive another app's window" premise — which is the entire product. Not worth it. Ship Developer ID.

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
