# Packaging — standalone desktop app

The app ships as a native desktop window using **PyWebView** (OS-native webview,
no Chromium) with the Python backend frozen by **PyInstaller**. The React UI is
built once to static files and bundled inside the executable.

```
desktop.py  ──spawns──▶  Flask (app.py) on a free localhost port
     │                        └─ extract_policies.py (pdfplumber + pandas + openpyxl)
     └──opens──▶  native window (WebView2 / WKWebView / WebKitGTK) → the Flask URL
```

## Run from source

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
python desktop.py
```

## Build a standalone binary

> PyInstaller **cannot cross-compile** — build each target on that OS (or use the
> included GitHub Actions workflow, which does all three).

```bash
pip install -r requirements-build.txt
cd frontend && npm install && npm run build && cd ..   # must run before freezing
pyinstaller desktop.spec
```

Output in `dist/`:

| OS | Artifact | How to run |
|----|----------|-----------|
| Windows | `dist/InsurancePolicyExtractor/InsurancePolicyExtractor.exe` | double-click |
| macOS | `dist/InsurancePolicyExtractor.app` | double-click |
| Linux | `dist/InsurancePolicyExtractor/InsurancePolicyExtractor` | `./InsurancePolicyExtractor` |

## Platform prerequisites (runtime webview)

- **Windows** — WebView2 Runtime. Present on Windows 11 and most updated Win10;
  if missing, install the Evergreen runtime from Microsoft.
- **macOS** — WKWebView is built in. Nothing to install.
- **Linux** — WebKitGTK:
  `sudo apt-get install libgtk-3-0 libwebkit2gtk-4.1-0 gir1.2-webkit2-4.1`
  and `pip install pygobject` in the build env.

## App icons

Icons live in `assets/` (`icon.ico` for Windows, `icon.icns` for macOS,
`icon.png` master). They're wired into `desktop.spec` automatically per platform.
To change the icon, replace those files (keep the names) and rebuild.

## CI builds for all three OS

Push a tag and GitHub Actions builds Windows/macOS/Linux artifacts **and
publishes them to a GitHub Release** (auto-generated release notes):

```bash
git tag v1.0.0
git push --tags
```

The binaries attach to the Release for that tag. You can also trigger the build
manually from the Actions tab (workflow_dispatch) — that run uploads artifacts
but does not create a Release (releases happen only on tag pushes).

## Known gotchas (already handled in `desktop.spec`)

- **pdfplumber / pdfminer.six data files** — bundled via `collect_all`; without
  them the frozen app reads zero text from PDFs.
- **Bundled React UI** — `app.py` resolves `frontend/dist` from `sys._MEIPASS`
  when frozen, and `desktop.spec` copies `frontend/dist` into the bundle.
- **openpyxl writer engine** — added as a hidden import so `df.to_excel` works.

## Code signing & distribution

Unsigned builds run fine locally but trigger warnings when shared:

- **macOS** — Gatekeeper blocks unsigned `.app`s. Right-click → Open to bypass
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

Not supported by this approach — PyWebView, PyInstaller, Electron and Tauri are
all desktop-only, and an embedded Flask server can't ship on the iOS App Store.
Mobile would require a separate rewrite (e.g. a hosted API + native/Flutter
client, or an on-device port of the extraction logic).
