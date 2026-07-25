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

### Why the Windows CI job is pinned to Python 3.8

CPython 3.9+ does not run on Windows 7 at all — this isn't just an installer
restriction, the interpreter itself won't launch there (Python 3.8 was the
last version to support it). PyInstaller bundles whichever Python built it,
so **the Windows build job in `.github/workflows/build.yml` must use Python
3.8** or the frozen `.exe` silently stops working on Windows 7 even though
`installer.iss`'s `MinVersion=6.1sp1` still lets the installer run there.
macOS/Linux have no such floor and stay on a current Python version.

If you ever bump the Windows job's Python version, either keep it at 3.8 or
explicitly drop Windows 7 from the supported-OS table above, the installer's
`MinVersion`, and this note — don't let them drift out of sync.

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
- **Universal C Runtime on Windows 7** — the frozen Python 3.8 exe links
  against `ucrtbase.dll` / `api-ms-win-crt-*.dll`, which ship built into
  Windows 10+ but aren't present on a stock Windows 7 SP1 install. Without
  them the exe fails to launch at all (`api-ms-win-crt-runtime-l1-1-0.dll was
  not found`), even though the installer itself runs fine down to
  `MinVersion=6.1sp1`. `installer.iss` bundles the VC++ 2015-2022 x64
  redistributable and installs it silently before first launch (skipped if
  already present — see `VCRedistNeedsInstall`). The CI job downloads
  `vc_redist.x64.exe` from Microsoft before running `iscc` (see
  `build.yml`); it isn't committed to the repo. Building the installer
  locally/manually needs the same file at `packaging\windows\vc_redist.x64.exe`
  — download it from https://aka.ms/vs/17/release/vc_redist.x64.exe first, or
  the installer will silently skip bundling it (`skipifsourcedoesntexist`).

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
