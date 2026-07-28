# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec for the Insurance Policy Extractor.

The app is a local Flask server that opens itself in the OS default browser
(see the __main__ block in app.py) — there is no native window / desktop UI,
so this just freezes app.py with its data files.

Build (run on the SAME OS you want to target — PyInstaller does not cross-compile):

    pip install -r requirements-build.txt
    cd frontend && npm install && npm run build && cd ..   # produces frontend/dist
    pyinstaller app.spec

Output lands in dist/ :
    Windows : dist/InsurancePolicyExtractor/InsurancePolicyExtractor.exe  (one-folder)
    macOS   : dist/InsurancePolicyExtractor/InsurancePolicyExtractor
    Linux   : dist/InsurancePolicyExtractor/InsurancePolicyExtractor
"""

import sys
from PyInstaller.utils.hooks import collect_all

# Per-platform icon: .ico for the Windows exe. No .app bundle on macOS since
# there's no window to give an icon to in the Dock beyond the running process.
EXE_ICON = "assets/icon.ico" if sys.platform == "win32" else None

datas = []
binaries = []
hiddenimports = []

# pdfplumber -> pdfminer.six ship data files (CMaps, glyphlists) that are loaded
# at runtime; without these the frozen app silently fails to read PDFs.
for pkg in ("pdfplumber", "pdfminer", "pdfdocument", "pypdfium2"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass  # package not present on this platform / version

# openpyxl + pandas writer engine
hiddenimports += ["openpyxl", "openpyxl.cell._writer"]

# Ship the prebuilt React UI. Mirrors app.py's DIST_DIR = BASE_DIR/frontend/dist
datas += [("frontend/dist", "frontend/dist")]

block_cipher = None

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InsurancePolicyExtractor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # runs silently; logs are visible in the UI (SSE) and
                              # app.py opens the default browser itself on start
    disable_windowed_traceback=False,
    target_arch=None,        # build for the host arch
    codesign_identity=None,
    entitlements_file=None,
    icon=EXE_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="InsurancePolicyExtractor",
)
