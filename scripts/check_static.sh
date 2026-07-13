#!/usr/bin/env bash
# check_static.sh — Static validation orchestrator.
# Delegates to leaf scripts so that local and CI share the same validation logic.
#
# Leaf scripts called:
#   check_compose.sh   — Docker Compose configuration validation
#   check_backend.sh   — ruff, pyright, pytest, import check (includes uv sync --locked)
#   check_frontend.sh  — prettier, eslint, tsc, vitest, next build (includes pnpm install)
#
# Does not require infrastructure to be running (tests are unit tests with mocked deps).
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== [static] Static validation ==="

"${SCRIPTS_DIR}/check_compose.sh"
"${SCRIPTS_DIR}/check_backend.sh"
"${SCRIPTS_DIR}/check_frontend.sh"

echo "=== [static] All static checks passed ==="
