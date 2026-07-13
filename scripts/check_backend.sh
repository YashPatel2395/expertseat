#!/usr/bin/env bash
# check_backend.sh — Backend checks: install, format, lint, typecheck, test, import check.
# Used by: check_static.sh (local), CI backend job.
# Assumes Python 3.12 and uv 0.11.7 are on PATH.
# DATABASE_URL and REDIS_URL are read from the environment (set by CI or .env locally).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${REPO_ROOT}/services/api"

echo "=== [backend] Backend checks ==="

echo "  [1/6] Install Python dependencies (locked)"
cd "${API_DIR}"
uv sync --locked --extra dev

echo "  [2/6] Format check (ruff)"
uv run ruff format --check .

echo "  [3/6] Lint (ruff)"
uv run ruff check .

echo "  [4/6] Type check (pyright)"
uv run pyright

echo "  [5/6] Tests (pytest)"
uv run pytest -v

echo "  [6/6] API import validation"
uv run python -c "from app.main import app; print('  API import OK')"

echo "=== [backend] All backend checks passed ==="
