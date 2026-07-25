#!/usr/bin/env bash
# Double-clickable launcher (macOS). Finder opens this in Terminal; it boots
# everything via run.sh (venv, deps, Ollama, UI build, server). Open
# http://127.0.0.1:5001 in a browser once it's running.
# Close the Terminal window (or press Ctrl+C) to stop the app.
cd "$(dirname "$0")"
exec ./run.sh
