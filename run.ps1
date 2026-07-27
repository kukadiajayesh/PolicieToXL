# One-command launcher for Windows (PowerShell 5.1+, including the version
# that ships on Windows 7 SP1 with the Windows Management Framework update).
# Installs Python deps if needed, builds the React UI if missing, starts the app.
$ErrorActionPreference = "Stop"
# $PSScriptRoot is empty on PowerShell 2.0 (Windows 7's default, pre-WMF update) — fall back to $MyInvocation.
$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $scriptRoot

# ── Python virtual environment ───────────────────────────────────────────────
# Running from source uses whatever `python` is on PATH — unlike the frozen
# CI build (pinned to 3.8 in .github/workflows/build.yml), this script can't
# force a specific interpreter. CPython 3.9+ won't even launch on Windows 7,
# so warn early instead of failing deep inside pip/venv with a confusing error.
$osVersion = [System.Environment]::OSVersion.Version
if ($osVersion.Major -eq 6 -and $osVersion.Minor -eq 1) {
    $pyVersionOutput = (python --version) 2>&1 | Out-String
    if ($pyVersionOutput -match "Python (\d+)\.(\d+)") {
        $pyMajor = [int]$Matches[1]; $pyMinor = [int]$Matches[2]
        if ($pyMajor -eq 3 -and $pyMinor -ge 9) {
            Write-Warning "Detected Windows 7 with Python $($Matches[0].Substring(7)) on PATH. CPython 3.9+ does not run on Windows 7 — install Python 3.8 (the last version that supports it) and make sure it's the one on PATH, or this will fail below."
        }
    }
}

if (-not (Test-Path ".venv")) {
    Write-Host "→ Creating virtual environment…"
    python -m venv .venv
}

Write-Host "→ Activating virtual environment…"
& ".\.venv\Scripts\Activate.ps1"

Write-Host "→ Checking Python dependencies…"
pip install -q -r requirements.txt

# ── React UI ─────────────────────────────────────────────────────────────────
if (-not (Test-Path "frontend\dist\index.html")) {
    Write-Host "→ Building React UI (first run only)…"
    Push-Location frontend
    npm install
    npm run build
    Pop-Location
}

Write-Host "→ Starting server at http://127.0.0.1:5001"
python app.py
