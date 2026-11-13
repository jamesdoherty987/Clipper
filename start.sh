#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r backend/requirements.txt
else
  source .venv/bin/activate
fi
export PYTHONPATH=backend
exec uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8787
