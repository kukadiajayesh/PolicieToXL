# Packaging — standalone binary

The app is a local Flask server viewed through the OS's **default
browser** — there's no native window, no bundled Chromium, and no GUI
toolkit dependency (WebView2 / WKWebView / WebKitGTK). The Python backend is
frozen by **PyInstaller**; the React UI is built once to static files and
bundled inside the executable.

```
app.py  ──serves──▶  frontend/dist (React UI) + /api/* (Flask)
                          └─ extract_policies.py (pdfplumber + pandas + openpyxl)
```

## Run from source

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
python app.py
```

This starts the server and prints its URL — open it in a browser. Ctrl+C in
the terminal stops the server.

## Build a standalone binary

> PyInstaller **cannot cross-compile** — build each target on that OS (or use the
> included GitHub Actions workflow, which builds all of them).

```bash
pip install -r requirements-build.txt
cd frontend && npm install && npm run build && cd ..   # must run before freezing
pyinstaller app.spec
```

This produces the raw one-folder build in `dist/`. For a real installable
artifact, run the platform packaging step on top of that (also done
automatically in CI):

| OS | Installable artifact | Packaging step |
|----|----------------------|-----------------|
| Windows | `InsurancePolicyExtractorSetup.exe` | `iscc packaging\windows\installer.iss` (Inno Setup) |
| macOS | `InsurancePolicyExtractor-<arch>.dmg` | `packaging/macos/make_dmg.sh <out.dmg>` |
| Linux | `InsurancePolicyExtractor-x86_64.AppImage` | `packaging/linux/make_appimage.sh <out.AppImage>` |

Raw portable builds (`dist/InsurancePolicyExtractor/…`, zipped/tarred) are
also produced in CI for users who prefer an unpacked folder.

## Supported OS versions

Because there's no native-webview dependency, support is simply "wherever a
frozen Python + a browser can run":

| OS | Versions |
|----|----------|
| Windows | 7 SP1, 8, 8.1, 10, 11 |
| macOS | 12 (Monterey) and later, Intel + Apple Silicon (two separate `.dmg`s, built on `macos-13` and `macos-latest` runners) |
| Linux | Any modern glibc distro (AppImage) |

The only runtime requirement on the target machine is *some* installed
browser (all of the above ship one by default) — nothing else to install.

### Why the Windows CI job is pinned to Python 3.8.2 exactly

CPython 3.9+ does not run on Windows 7 at all — this isn't just an installer
restriction, the interpreter itself won't launch there. But **not just any
3.8.x** works either: 3.8.3 and later were built with a newer MSVC toolset
that pulled in a dependency on `api-ms-win-core-path-l1-1-0.dll`, an
api-set that Windows 7 has no way to resolve (see the "Known gotchas" entry
below) — so those patch releases silently fail to launch on Windows 7 too,
even though python.org still lists all of 3.8 as Windows-7-compatible.
**3.8.2 is the last patch release built without that dependency.**

PyInstaller bundles whichever Python built it, so **the Windows build job in
`.github/workflows/build.yml` must use exactly Python 3.8.2** (both the x64
and x86 legs) or the frozen `.exe` silently stops working on Windows 7 even
though `installer.iss`'s `MinVersion=6.1sp1` still lets the installer run
there. macOS/Linux have no such floor and stay on a current Python version.

If you ever bump the Windows job's Python version, either keep it at exactly
3.8.2 or explicitly drop Windows 7 from the supported-OS table above, the
installer's `MinVersion`, and this note — don't let them drift out of sync.
`build_installer.ps1` (the local/manual build path) does **not** enforce
this pin itself — see the note at the top of that script.

All of `app.py` and `extract_policies.py` use `from __future__ import
annotations` specifically so their type hints (`X | None`, `list[...]`,
`dict[...]`) — which need Python 3.9/3.10+ to *evaluate* — still work when
frozen with 3.8. Keep that import if you add more modules with modern type
hints to the frozen app.

`run.ps1` / `run.sh` (the "run from source" launchers) warn rather than fail
outright when the Python on PATH is too new for Windows 7, since the app's
only extraction engine (Gemini) needs no local runtime beyond Python itself.

## App icons

Icons live in `assets/` (`icon.ico` for Windows, `icon.png` used for the
Linux AppImage). They're wired into `app.spec` / `packaging/windows/installer.iss`
/ `packaging/linux/make_appimage.sh`. To change the icon, replace those files
(keep the names) and rebuild.

## CI builds for all platforms

Push a tag and GitHub Actions builds the Windows installer, both macOS dmgs,
and the Linux AppImage (plus portable zip/tar.gz fallbacks) and **publishes
them all to a GitHub Release** (auto-generated release notes):

```bash
git tag v1.0.0
git push --tags
```

The version in the tag (`v1.0.0` → `1.0.0`) is threaded into the Windows
installer's `AppVersion` via the `APP_VERSION` env var.

The binaries attach to the Release for that tag. You can also trigger the build
manually from the Actions tab (workflow_dispatch) — that run uploads artifacts
but does not create a Release (releases happen only on tag pushes).

## Known gotchas (already handled in `app.spec`)

- **pdfplumber / pdfminer.six data files** — bundled via `collect_all`; without
  them the frozen app reads zero text from PDFs.
- **Bundled React UI** — `app.py` resolves `frontend/dist` from `sys._MEIPASS`
  when frozen, and `app.spec` copies `frontend/dist` into the bundle.
- **openpyxl writer engine** — added as a hidden import so `df.to_excel` works.
- **`console=True`** in `app.spec` — there's no window UI, so the console is
  the only way to see server logs and stop the app (Ctrl+C). The Linux
  `.desktop` entry sets `Terminal=true` for the same reason.
- **Universal C Runtime on Windows 7** — the frozen Python exe links against
  `ucrtbase.dll` / `api-ms-win-crt-*.dll`, which ship built into Windows 10+
  but aren't present on a stock Windows 7 SP1 install. Without them the exe
  fails to launch at all (`api-ms-win-crt-runtime-l1-1-0.dll was not found`),
  even though the installer itself runs fine down to `MinVersion=6.1sp1`.
  `installer.iss` bundles the VC++ 2015-2022 x64/x86 redistributables and
  installs them silently before first launch (skipped if already present —
  see `VCRedistNeedsInstall`). The CI job downloads `vc_redist.x64.exe` /
  `vc_redist.x86.exe` from Microsoft before running `iscc` (see `build.yml`);
  they aren't committed to the repo. Building the installer locally/manually
  needs the same files at `packaging\windows\vc_redist.x64.exe` /
  `vc_redist.x86.exe` — download from https://aka.ms/vs/17/release/vc_redist.x64.exe
  and https://aka.ms/vs/17/release/vc_redist.x86.exe first, or the installer
  will silently skip bundling them (`skipifsourcedoesntexist`).

- **`api-ms-win-core-path-l1-1-0.dll` missing on Windows 7** — a *different*
  DLL from the one above, and easy to mistake for the same UCRT issue since
  the error looks identical (`The program can't start because
  api-ms-win-core-path-l1-1-0.dll is missing`). This one is not a UCRT
  component — it's an OS-level api-set forwarder that Windows 8+ resolves
  virtually via the in-box ApiSet Schema, which Windows 7 doesn't have at
  all. Microsoft never shipped a redistributable stub for it on Windows 7
  (unlike the `api-ms-win-crt-*` ones above, which `vc_redist` does cover).
  CPython 3.8.3+ started linking against it due to a build-toolset bump,
  which silently breaks real Windows 7 support for those patch releases even
  though python.org still lists all of 3.8 as Windows-7-compatible. The fix
  is upstream, not packaging: freeze with **exactly Python 3.8.2** (the last
  patch release built without this dependency) — see "Why the Windows CI job
  is pinned to Python 3.8.2 exactly" above. If you hit this error after
  building locally, check the Python version(s) passed to
  `build_installer.ps1`.

## Code signing & distribution

Unsigned builds run fine locally but trigger warnings when shared:

- **macOS** — Gatekeeper blocks unsigned apps. Right-click → Open to bypass
  for personal use, or sign + notarize with an Apple Developer ID for
  distribution.
- **Windows** — SmartScreen warns on unsigned `.exe`s. An Authenticode
  certificate removes the warning.

For personal/internal use, signing is optional. For wider distribution, add the
certs and set `codesign_identity` / a signing step in CI.

## Bundle size

Expect ~80–120 MB, driven mostly by pandas/numpy and the Python runtime.
This is normal for a frozen scientific-Python app.

## iOS / mobile

Not supported by this approach — PyInstaller freezes a desktop Python
process, and an embedded Flask server can't ship on the iOS App Store.
Mobile would require a separate rewrite (e.g. a hosted API + native/Flutter
client, or an on-device port of the extraction logic).
