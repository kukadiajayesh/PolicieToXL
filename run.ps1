# One-command launcher for Windows (PowerShell 5.1+).
# Installs Ollama + Python deps if needed, builds the React UI if missing, starts the app.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$DEFAULT_OLLAMA_MODEL = "llama3.2"

# ── Ollama: install if missing ───────────────────────────────────────────────
function Install-Ollama {
    Write-Host "→ Ollama not found — installing…"

    # Try winget first (available on Windows 10 1709+ and Windows 11)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Using winget…"
        winget install Ollama.Ollama --silent --accept-source-agreements --accept-package-agreements
    } else {
        # Fall back to direct installer download
        $installer = "$env:TEMP\OllamaSetup.exe"
        Write-Host "  Downloading OllamaSetup.exe…"
        Invoke-WebRequest `
            -Uri "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe" `
            -OutFile $installer `
            -UseBasicParsing
        Write-Host "  Running installer (silent)…"
        Start-Process -FilePath $installer -ArgumentList "/S" -Wait
    }

    # Refresh PATH in this session so 'ollama' is found immediately
    $machine = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
    $user    = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $env:PATH = "$machine;$user"
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Install-Ollama
}

# Verify install succeeded
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Error "Ollama installation failed or PATH was not updated. Please restart this terminal and try again."
    exit 1
}

# ── Ollama: start server if not already running ──────────────────────────────
$ollamaRunning = $false
try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null
    $ollamaRunning = $true
} catch {}

if (-not $ollamaRunning) {
    Write-Host "→ Starting Ollama server…"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden

    $ready = $false
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        try {
            Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch {}
    }
    if (-not $ready) {
        Write-Error "Ollama server did not start in time. Run 'ollama serve' manually and retry."
        exit 1
    }
}

# ── Ollama: pull default model if not already present ───────────────────────
$installedModels = ollama list 2>$null | Out-String
if ($installedModels -notmatch [regex]::Escape($DEFAULT_OLLAMA_MODEL)) {
    Write-Host "→ Pulling $DEFAULT_OLLAMA_MODEL (first run only — this may take a few minutes)…"
    ollama pull $DEFAULT_OLLAMA_MODEL
}

# ── Python virtual environment ───────────────────────────────────────────────
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
