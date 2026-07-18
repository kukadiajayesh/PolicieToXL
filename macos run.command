#!/usr/bin/env bash
# Double-clickable launcher (macOS). Finder opens this in Terminal; it boots
# everything via run.sh (venv, deps, Ollama, UI build, server) and run.sh
# opens the app in the browser as soon as the server answers.
# Close the Terminal window (or press Ctrl+C) to stop the app.
cd "$(dirname "$0")"
exec ./run.sh
