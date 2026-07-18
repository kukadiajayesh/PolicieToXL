#!/usr/bin/env bash
# Double-clickable/launchable launcher (Linux). Boots everything via run.sh
# (venv, deps, Ollama, UI build, server) and run.sh opens the app in the
# default browser (xdg-open) as soon as the server answers.
# Close the terminal (or press Ctrl+C) to stop the app.
cd "$(dirname "$0")"
exec ./run.sh
