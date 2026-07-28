# Builds the Windows installer (InsurancePolicyExtractorSetup.exe) from source.
# Mirrors the Windows job in .github/workflows/build.yml, but run locally.
#
# Produces ONE installer that bundles both a 64-bit and a 32-bit build of the
# app, so it installs on x86 (win32) Windows as well as x64. This requires a
# SECOND, 32-bit Python interpreter in addition to the normal (64-bit) one on
# PATH — point -Python32Path at it if it's not at the default location.
#
# The 32-bit interpreter must be Python 3.11 or older: pandas has not shipped
# a win32 wheel since 2.0.3, and 2.0.3's own win32 wheels stop at cp311 — so
# nothing newer can install pandas on 32-bit Windows without a full MSVC
# toolchain to compile it from source. constraints-x86.txt pins pandas (and
# cryptography) to the last win32-capable versions for this leg; a 32-bit
# Python 3.12+ will simply fail to resolve them.
#
# NOTE — Windows 7 support: unlike the CI job in .github/workflows/build.yml
# (which pins BOTH interpreters to exactly Python 3.8.2), this local script
# just uses whatever "python" is on PATH plus whatever -Python32Path points
# at. If either is newer than 3.8.2, the resulting build will not run on
# Windows 7 — 3.9+ won't launch there at all, and 3.8.3+ pulls in
# api-ms-win-core-path-l1-1-0.dll, an api-set Windows 7 has no way to
# resolve (see PACKAGING.md's "Known gotchas" section). Point both PATH's
# python and -Python32Path at Python 3.8.2 installs if you need the local
# build to support Windows 7; otherwise this script is fine for a
# Windows-10+-only build.
#
# Usage:
#   build_installer.bat                                # version defaults to 1.0.0
#   build_installer.bat 1.2.0                           # explicit version
#   build_installer.ps1 -Version 1.2.0 -Python32Path "C:\Python311-32\python.exe"
param(
    [string]$Version = "1.0.0",
    [string]$Python32Path = "C:\Python311-32\python.exe"
)

$ErrorActionPreference = "Stop"
$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $scriptRoot

function Fail($msg) {
    Write-Host "FAILED: $msg" -ForegroundColor Red
    exit 1
}

# ── Prerequisites ─────────────────────────────────────────────────────────
$isccCmd = Get-Command iscc -ErrorAction SilentlyContinue
if ($isccCmd) {
    $isccPath = $isccCmd.Source
} else {
    $defaultIscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (Test-Path $defaultIscc) {
        $isccPath = $defaultIscc
    } else {
        Fail "Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php (or 'choco install innosetup'), then re-run."
    }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "Python (64-bit) not found on PATH."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail "npm not found on PATH - install Node.js first."
}
if (-not (Test-Path $Python32Path)) {
    Fail "32-bit Python not found at '$Python32Path'. Install a win32 Python build (python.org offers python-<ver>.exe, the plain non-'amd64' installer) and/or pass -Python32Path."
}

# ── React UI (shared by both architectures, always rebuilt so the installer
#    ships the latest frontend) ────────────────────────────────────────────
Write-Host "-> Building React UI..."
Push-Location frontend
npm install
npm run build
Pop-Location

# ── Per-architecture: venv + build deps + PyInstaller freeze ───────────────
function Build-Arch {
    param(
        [string]$Arch,           # "x64" or "x86"
        [string]$PythonExe,      # path/name of the interpreter to build with
        [string]$VenvDir,
        [string]$ConstraintsFile = $null
    )

    Write-Host "-> [$Arch] Setting up virtual environment ($VenvDir)..."
    if (-not (Test-Path $VenvDir)) {
        & $PythonExe -m venv $VenvDir
    }
    $venvPython = Join-Path $VenvDir "Scripts\python.exe"

    Write-Host "-> [$Arch] Upgrading pip..."
    & $venvPython -m pip install -q --upgrade pip
    if ($LASTEXITCODE -ne 0) { Fail "[$Arch] pip upgrade failed." }

    Write-Host "-> [$Arch] Installing build dependencies..."
    if ($ConstraintsFile) {
        & $venvPython -m pip install -q -r requirements-build.txt -c $ConstraintsFile
    } else {
        & $venvPython -m pip install -q -r requirements-build.txt
    }
    if ($LASTEXITCODE -ne 0) { Fail "[$Arch] pip install failed." }

    Write-Host "-> [$Arch] Freezing app with PyInstaller..."
    if (Test-Path "dist\InsurancePolicyExtractor") {
        Remove-Item -Recurse -Force "dist\InsurancePolicyExtractor"
    }
    $distArchDir = "dist\InsurancePolicyExtractor-$Arch"
    if (Test-Path $distArchDir) {
        Remove-Item -Recurse -Force $distArchDir
    }
    & $venvPython -m PyInstaller app.spec
    if ($LASTEXITCODE -ne 0) { Fail "[$Arch] PyInstaller failed." }
    if (-not (Test-Path "dist\InsurancePolicyExtractor\InsurancePolicyExtractor.exe")) {
        Fail "[$Arch] PyInstaller did not produce dist\InsurancePolicyExtractor\InsurancePolicyExtractor.exe"
    }
    Move-Item "dist\InsurancePolicyExtractor" $distArchDir
}

Build-Arch -Arch "x64" -PythonExe "python" -VenvDir ".venv" -ConstraintsFile "constraints-x64.txt"
Build-Arch -Arch "x86" -PythonExe $Python32Path -VenvDir ".venv32" -ConstraintsFile "constraints-x86.txt"

# ── VC++ redistributables (bundled for Windows 7; skipped if unreachable) ──
$vcRedists = @{
    "packaging\windows\vc_redist.x64.exe" = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    "packaging\windows\vc_redist.x86.exe" = "https://aka.ms/vs/17/release/vc_redist.x86.exe"
}
foreach ($path in $vcRedists.Keys) {
    if (-not (Test-Path $path)) {
        Write-Host "-> Downloading $(Split-Path -Leaf $path) (for Windows 7 support)..."
        try {
            Invoke-WebRequest -Uri $vcRedists[$path] -OutFile $path
        } catch {
            Write-Warning "Could not download $(Split-Path -Leaf $path) - the installer will skip bundling it (Windows 10/11 targets are unaffected)."
        }
    }
}

# ── Inno Setup installer ────────────────────────────────────────────────────
Write-Host "-> Building installer (version $Version)..."
$env:APP_VERSION = $Version
& $isccPath "packaging\windows\installer.iss"
if ($LASTEXITCODE -ne 0) {
    Fail "ISCC.exe failed (exit code $LASTEXITCODE)."
}

$output = "packaging\windows\Output\InsurancePolicyExtractorSetup.exe"
if (Test-Path $output) {
    Write-Host "DONE: Installer built at $output" -ForegroundColor Green
} else {
    Fail "Expected output not found at $output"
}
