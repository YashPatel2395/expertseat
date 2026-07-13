#!/usr/bin/env bash
# check_static.sh — Static validation: format, lint, typecheck, tests, build, import check.
# Does not require infrastructure to be running.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${REPO_ROOT}/services/api"

echo "=== [static] Static validation ==="

echo "  [1/11] Validate Docker Compose configuration"
docker compose -f "${REPO_ROOT}/infrastructure/docker-compose.yml" config --quiet

echo "  [2/11] Backend format check (ruff)"
cd "${API_DIR}" && uv run ruff format --check .

echo "  [3/11] Frontend format check (prettier)"
cd "${REPO_ROOT}" && pnpm run --filter web format:check

echo "  [4/11] Backend lint (ruff)"
cd "${API_DIR}" && uv run ruff check .

echo "  [5/11] Frontend lint (eslint)"
cd "${REPO_ROOT}" && pnpm run --filter web lint

echo "  [6/11] Backend type check (pyright)"
cd "${API_DIR}" && uv run pyright

echo "  [7/11] Frontend type check (tsc)"
cd "${REPO_ROOT}" && pnpm run --filter web typecheck

echo "  [8/11] Backend tests (pytest)"
cd "${API_DIR}" && uv run pytest -v

echo "  [9/11] Frontend tests (vitest)"
cd "${REPO_ROOT}" && pnpm run --filter web test

echo "  [10/11] Frontend production build (next build)"
cd "${REPO_ROOT}" && pnpm run --filter web build

echo "  [11/11] Backend import validation"
cd "${API_DIR}" && uv run python -c "from app.main import app; print('  API import OK')"

echo "=== [static] All static checks passed ==="
