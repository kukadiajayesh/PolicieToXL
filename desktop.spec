# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec for the Insurance Policy Extractor desktop app.

Build (run on the SAME OS you want to target — PyInstaller does not cross-compile):

    pip install -r requirements.txt
    cd frontend && npm install && npm run build && cd ..   # produces frontend/dist
    pyinstaller desktop.spec

Output lands in dist/ :
    Windows : dist/InsurancePolicyExtractor/InsurancePolicyExtractor.exe  (one-folder)
    macOS   : dist/InsurancePolicyExtractor.app
    Linux   : dist/InsurancePolicyExtractor/InsurancePolicyExtractor
"""

import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files

# Per-platform icon: .ico for the Windows exe, .icns for the macOS bundle.
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
    ["desktop.py"],
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
    console=False,          # no terminal window; it's a GUI app
    disable_windowed_traceback=False,
    target_arch=None,       # build for the host arch
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

# macOS: wrap the one-folder build into a proper .app bundle.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="InsurancePolicyExtractor.app",
        icon="assets/icon.icns",
        bundle_identifier="com.local.insurancepolicyextractor",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )
