#!/usr/bin/env bash
# One-command launcher for ALMS (Linux / WSL / macOS).
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3 not found. On Ubuntu/WSL run:  sudo apt update && sudo apt install -y python3 python3-venv"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: creating virtual environment…"
  if ! "$PY" -m venv .venv 2>/dev/null; then
    rm -rf .venv
    echo "python3-venv is missing. On Ubuntu/WSL run:  sudo apt update && sudo apt install -y python3-venv"
    exit 1
  fi
fi

if [ ! -f .venv/.deps-installed ] || [ requirements.txt -nt .venv/.deps-installed ]; then
  echo "Installing dependencies…"
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  touch .venv/.deps-installed
fi

exec .venv/bin/python run.py "$@"
