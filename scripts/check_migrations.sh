#!/usr/bin/env bash
# check_migrations.sh — Database migration cycle: install, upgrade → downgrade → upgrade.
# Used by: CI migrations job.
# Assumes Python 3.12, uv 0.11.7, and a reachable PostgreSQL instance are available.
# DATABASE_URL must be set in the environment.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${REPO_ROOT}/services/api"

echo "=== [migrations] Migration cycle ==="

echo "  [1/4] Install Python dependencies (locked)"
cd "${API_DIR}"
uv sync --locked --extra dev

echo "  [2/4] Alembic upgrade to head"
uv run alembic upgrade head

echo "  [3/4] Alembic downgrade to base"
uv run alembic downgrade base

echo "  [4/4] Alembic re-upgrade to head"
uv run alembic upgrade head

echo "=== [migrations] Migration cycle passed ==="
