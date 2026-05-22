#!/usr/bin/env bash
# Boot backend in --reload mode against .env in backend/.
# Usage: ./scripts/dev-backend.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/backend"

if [ ! -d ".venv" ]; then
    echo "Creating venv..."
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

if [ ! -f ".env" ]; then
    echo "Warning: no backend/.env — copy .env.example and fill in tokens." >&2
fi

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
