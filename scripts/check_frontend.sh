#!/usr/bin/env bash
# check_frontend.sh — Frontend checks: install, format, lint, typecheck, test, build.
# Used by: check_static.sh (local), CI frontend job.
# Assumes Node.js 24 and pnpm 11.12.0 are on PATH.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== [frontend] Frontend checks ==="

echo "  [1/6] Install npm dependencies (frozen lockfile)"
cd "${REPO_ROOT}"
pnpm install --frozen-lockfile

echo "  [2/6] Format check (prettier)"
pnpm run --filter web format:check

echo "  [3/6] Lint (eslint)"
pnpm run --filter web lint

echo "  [4/6] Type check (tsc)"
pnpm run --filter web typecheck

echo "  [5/6] Tests (vitest)"
pnpm run --filter web test

echo "  [6/6] Production build (next build)"
pnpm run --filter web build

echo "=== [frontend] All frontend checks passed ==="
