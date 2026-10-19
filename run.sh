#!/usr/bin/env bash
# One command: sets everything up the first time, then starts the app.
#   ./run.sh           start the app
#   ./run.sh --demo    also build the demo class (downloads public LFW faces once)
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: creating Python environment..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi
.venv/bin/python scripts/download_models.py
if [ "$1" = "--demo" ] && [ ! -f demo/class_photo.jpg ]; then
  .venv/bin/python scripts/make_demo_class.py
fi
( sleep 2; command -v open >/dev/null && open "http://localhost:8000" ) &
.venv/bin/python app/server.py
