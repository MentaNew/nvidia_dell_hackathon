#!/usr/bin/env bash
# Start RescueBase (API + UI) on http://localhost:8000. Creates .venv on first run. Works on Linux and Git Bash.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=$(command -v python3 || command -v python)
[ -d .venv ] || "$PY" -m venv .venv
VPY=.venv/bin/python; [ -x "$VPY" ] || VPY=.venv/Scripts/python
"$VPY" -m pip install -q -r requirements.txt
exec "$VPY" -m uvicorn backend.app:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
