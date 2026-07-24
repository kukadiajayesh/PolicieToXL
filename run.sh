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

# ── Open default browser once the server answers ────────────────────────────
_open_browser() {
  local url="$1"
  if [[ "$OSTYPE" == "darwin"* ]]; then
    open "$url"
  elif command -v xdg-open &>/dev/null; then
    xdg-open "$url" >/dev/null 2>&1
  elif command -v wslview &>/dev/null; then
    wslview "$url"
  fi
}

URL="http://127.0.0.1:5001"
(
  for _ in $(seq 1 60); do
    if curl -sf "$URL" >/dev/null 2>&1; then
      _open_browser "$URL"
      break
    fi
    sleep 1
  done
) &

echo "→ Starting server at http://127.0.0.1:5001"
python3 app.py
