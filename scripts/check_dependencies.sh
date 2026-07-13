#!/usr/bin/env bash
# check_dependencies.sh — Dependency vulnerability audit: pip-audit (Python CVEs) and
# pnpm audit (npm CVEs). These are separate concerns from secret scanning.
# Used by: check_security.sh (local), CI audit job.
# Assumes Python 3.12, uv 0.11.7, Node.js 24, and pnpm 11.12.0 are on PATH.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${REPO_ROOT}/services/api"

echo "=== [dependencies] Dependency vulnerability audit ==="

echo "  [1/4] Install Python dependencies (locked)"
cd "${API_DIR}"
uv sync --locked --extra dev

echo "  [2/4] Python dependency audit (pip-audit)"
uv run pip-audit
echo "  pip-audit: no known CVEs"

echo "  [3/4] Install npm dependencies (frozen lockfile)"
cd "${REPO_ROOT}"
pnpm install --frozen-lockfile

echo "  [4/4] npm dependency audit (high and critical)"
pnpm audit --audit-level high
echo "  pnpm audit: no high/critical CVEs"

echo "=== [dependencies] All dependency audits passed ==="
