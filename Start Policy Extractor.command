#!/usr/bin/env bash
# Double-clickable launcher (macOS). Finder opens this in Terminal; it boots
# everything via run.sh (venv, deps, Ollama, UI build) and opens the app in
# the browser as soon as the server answers. Close the Terminal window (or
# press Ctrl+C) to stop the app.
cd "$(dirname "$0")"

URL="http://127.0.0.1:5001"

# run.sh blocks in the foreground, so watch for the server from the background
# and open the UI once it's up. If the app is already running from an earlier
# double-click, this just opens a tab to the existing instance.
(
  for _ in $(seq 1 120); do
    if curl -sf "$URL" >/dev/null 2>&1; then
      open "$URL"
      exit 0
    fi
    sleep 1
  done
) &

exec ./run.sh
