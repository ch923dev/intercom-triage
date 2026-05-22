#!/usr/bin/env bash
# Seed (or reset) the local SQLite DB.
# Usage:  ./scripts/seed-db.sh
#         ./scripts/seed-db.sh --reset
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/backend"

if [ ! -d ".venv" ]; then
    echo "No .venv — run scripts/dev-backend.sh once to create it." >&2
    exit 1
fi
source .venv/bin/activate

if [ "${1:-}" = "--reset" ]; then
    rm -f data/triage.db data/triage.db-journal data/triage.db-wal data/triage.db-shm
    echo "Wiped data/triage.db*"
fi

python -m app.models
