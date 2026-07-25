#!/usr/bin/env bash
# Double-clickable/launchable launcher (Linux). Boots everything via run.sh
# (venv, deps, Ollama, UI build, server). Open http://127.0.0.1:5001 in a
# browser once it's running.
# Close the terminal (or press Ctrl+C) to stop the app.
cd "$(dirname "$0")"
exec ./run.sh
