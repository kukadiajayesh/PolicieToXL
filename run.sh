#!/usr/bin/env bash
# One-command launcher (macOS / Linux).
# Installs Python deps if needed, builds the React UI if missing, starts the app.
set -e
cd "$(dirname "$0")"

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
