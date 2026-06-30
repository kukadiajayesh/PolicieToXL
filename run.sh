#!/usr/bin/env bash
# One-command launcher (macOS / Linux).
# Installs Ollama + Python deps if needed, builds the React UI if missing, starts the app.
set -e
cd "$(dirname "$0")"

DEFAULT_OLLAMA_MODEL="llama3.2"

# ── Ollama: install if missing ───────────────────────────────────────────────
_install_ollama_mac() {
  local arch install_dir
  arch="$(uname -m)"           # arm64 (Apple Silicon) or x86_64 (Intel)
  install_dir="$HOME/.local/bin"
  mkdir -p "$install_dir"

  echo "→ Downloading Ollama binary for macOS ($arch)…"
  if [[ "$arch" == "arm64" ]]; then
    curl -fL "https://github.com/ollama/ollama/releases/latest/download/ollama-darwin-arm64" \
      -o "$install_dir/ollama" 2>/dev/null \
      || curl -fL "https://github.com/ollama/ollama/releases/latest/download/ollama-darwin" \
        -o "$install_dir/ollama"
  else
    curl -fL "https://github.com/ollama/ollama/releases/latest/download/ollama-darwin-amd64" \
      -o "$install_dir/ollama" 2>/dev/null \
      || curl -fL "https://github.com/ollama/ollama/releases/latest/download/ollama-darwin" \
        -o "$install_dir/ollama"
  fi

  chmod +x "$install_dir/ollama"
  export PATH="$install_dir:$PATH"
  echo "  Installed to $install_dir/ollama"
  echo "  Add $install_dir to your PATH to use 'ollama' in future sessions."
}

_install_ollama_linux() {
  echo "→ Installing Ollama via official installer…"
  curl -fsSL https://ollama.com/install.sh | sh
}

if ! command -v ollama &>/dev/null; then
  echo "→ Ollama not found — installing…"
  if [[ "$OSTYPE" == "darwin"* ]]; then
    _install_ollama_mac
  else
    _install_ollama_linux
  fi
fi

# ── Ollama: start server if not already running ──────────────────────────────
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "→ Starting Ollama server…"
  ollama serve >/dev/null 2>&1 &
  for i in $(seq 1 15); do
    sleep 1
    curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break
    if [ "$i" -eq 15 ]; then
      echo "  Ollama server did not start in time. Run 'ollama serve' manually and retry."
      exit 1
    fi
  done
fi

# ── Ollama: pull default model if not already present ───────────────────────
if ! ollama list 2>/dev/null | grep -q "^${DEFAULT_OLLAMA_MODEL}"; then
  echo "→ Pulling ${DEFAULT_OLLAMA_MODEL} (first run only — this may take a few minutes)…"
  ollama pull "$DEFAULT_OLLAMA_MODEL"
fi

# ── Python virtual environment ───────────────────────────────────────────────
if [ ! -d .venv ]; then
  echo "→ Creating virtual environment…"
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "→ Checking Python dependencies…"
pip install -q -r requirements.txt

# ── React UI ─────────────────────────────────────────────────────────────────
if [ ! -f frontend/dist/index.html ]; then
  echo "→ Building React UI (first run only)…"
  ( cd frontend && npm install && npm run build )
fi

echo "→ Starting server at http://127.0.0.1:5001"
python3 app.py
