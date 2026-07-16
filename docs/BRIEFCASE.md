# Packaging for the Mac App Store / TestFlight with Briefcase

This is the chosen packaging route after the py2app spike failed under the App
Sandbox (see [DISTRIBUTION.md](DISTRIBUTION.md) → "Packaging spike"). Briefcase
(BeeWare) is purpose-built to produce signed, sandboxed, App-Store-uploadable
Python-GUI bundles and handles the Qt-plugin / launch / entitlements wiring that
py2app does not.

**Do this interactively at the Mac** — it needs a full **Xcode** install and the
GUI (Gatekeeper, LaunchServices, App Store Connect). It cannot be driven
head-less.

## Prerequisites

- Full **Xcode** (not just Command Line Tools) — the App Store path uses
  Briefcase's Xcode-project format.
- Apple Developer Program enrollment (already done — team `H3425WJ3TM`).
- `pip install briefcase` into a clean venv.
- The Briefcase config already scaffolded in `pyproject.toml` (`[tool.briefcase]`).

## Build & run locally (dev loop)

```bash
briefcase dev                    # run from source under Briefcase (verify entry point)
briefcase create macOS Xcode     # generate the Xcode project (bundles Python + Qt)
briefcase build  macOS Xcode
briefcase run    macOS Xcode     # launches the packaged app to smoke-test
```

At `briefcase dev` / first `create`, confirm the app entry point resolves
(current source entry is `src/main.py:main()`; Briefcase expects the app's
`__main__` — may need a small shim or a `main_module` setting in `pyproject.toml`).

## App Store submission (verified process, 2026-07-16)

Source: [Briefcase macOS publishing guide](https://briefcase.beeware.org/en/latest/how-to/publishing/macOS/).

1. `briefcase open macOS Xcode` — opens the generated project in Xcode.
2. In Xcode → the root project node → **Signing & Capabilities** → select your
   development **team** (`H3425WJ3TM`). Briefcase's Xcode template lets Xcode
   manage the App Store signing identities + provisioning profile — you do **not**
   need to pre-generate the Apple Distribution / Mac Installer Distribution certs
   by hand; an Apple ID in the developer program is enough.
3. Confirm the **App Sandbox** capability is present (it comes from the
   `com.apple.security.app-sandbox` entitlement set in `pyproject.toml`).
4. **Product → Archive**.
5. In the Organizer, select the archive → **Distribute App** → App Store Connect.
6. In App Store Connect: create the app record (Bundle ID `br.com.raphaelbgr.iosautoclicker`,
   an SKU), fill metadata (category, description, privacy policy), and complete
   the **App Privacy** questionnaire (both are UI-only — not scriptable, per the
   vault's App Store Connect gotchas).
7. Under **Build**, select the uploaded archive.
8. **TestFlight**: add an internal group + testers → they get the build with **no
   Beta App Review**. External testers / public release require Beta/App Review
   (where the "Accessibility for game automation" policy risk applies — see
   DISTRIBUTION.md §4).

## Still-open items before this will build clean

- **App entry point** for Briefcase (see above).
- **App icon**: point `icon =` at the existing `.iconset` / `.icns`.
- **ScreenCaptureKit port** (step 2): the current `CGWindowListCreateImage`
  capture must move to ScreenCaptureKit for a sandboxed build; verify whether a
  `com.apple.security.screen-capture` entitlement is then required.
- **Data dirs**: already relocated — `projects/`, `logs/`, `tracks/` now resolve
  to Application Support when frozen (`src/paths.py`), which the sandbox redirects
  into the app container. Nothing writes inside the read-only bundle anymore.
