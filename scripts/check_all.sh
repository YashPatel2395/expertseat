#!/usr/bin/env bash
# check_all.sh — Full quality gate for ExpertSeat.
#
# Runs all validation phases in order by calling shared leaf scripts.
# CI jobs call the same leaf scripts, so local and CI use identical validation logic.
#
#   Phase 1 — check_versions.sh         version checks + dependency installation
#   Phase 2 — check_static.sh           orchestrates:
#               check_compose.sh        Docker Compose configuration validation
#               check_backend.sh        ruff, pyright, pytest, import check
#               check_frontend.sh       prettier, eslint, tsc, vitest, next build
#   Phase 3 — check_infrastructure.sh   Docker Compose up, migration cycle
#   Phase 4 — check_runtime.sh          HTTP liveness/readiness, degradation, recovery
#   Phase 5 — check_security.sh         orchestrates:
#               check_secrets.sh        Gitleaks 8.30.1 full history scan
#               check_dependencies.sh   pip-audit + pnpm audit
#   Phase 6 — cleanup
#
# Must be run from the repository root or from scripts/.
# Requires: Docker, Node.js 24, pnpm 11.12.0, Python 3.12, uv 0.11.7, gitleaks 8.30.1.
#
# Usage:
#   scripts/check_all.sh         (or: make check)
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPTS_DIR}/.." && pwd)"
COMPOSE="docker compose -f ${REPO_ROOT}/infrastructure/docker-compose.yml"
UVICORN_PID_FILE="/tmp/expertseat-uvicorn.pid"

# ─── Master cleanup ────────────────────────────────────────────────────────────
# Runs on any exit (success or failure) to ensure no orphaned processes or
# containers are left behind.

cleanup_all() {
  local EXIT_CODE=$?
  echo ""
  echo "=== [cleanup] Cleanup ==="

  # Stop Uvicorn if running
  if [ -f "${UVICORN_PID_FILE}" ]; then
    local PID
    PID=$(cat "${UVICORN_PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
      kill "${PID}" 2>/dev/null || true
      echo "  [51] Uvicorn stopped."
    fi
    rm -f "${UVICORN_PID_FILE}"
  fi

  # Stop all Docker Compose services
  ${COMPOSE} down --volumes 2>/dev/null || true
  echo "  [52] Docker Compose services stopped."

  # Remove temporary files
  rm -f /tmp/expertseat-uvicorn.log /tmp/expertseat-readiness-check.json
  echo "  [53] Temporary files removed."

  echo "  [54] Cleanup complete."

  if [ "${EXIT_CODE}" -ne 0 ]; then
    echo ""
    echo "================================================================"
    echo " Quality gate FAILED (exit code ${EXIT_CODE})"
    echo "================================================================"
  fi

  return "${EXIT_CODE}"
}
trap cleanup_all EXIT

echo "================================================================"
echo " ExpertSeat — quality gate"
echo "================================================================"
echo ""

# Phase 1: Version checks and dependency installation
"${SCRIPTS_DIR}/check_versions.sh"
echo ""

# Phase 2: Static validation — compose, backend, frontend
"${SCRIPTS_DIR}/check_static.sh"
echo ""

# Phase 3: Infrastructure and migrations
# CLEANUP_INFRA=false so services remain running for check_runtime.sh
CLEANUP_INFRA=false "${SCRIPTS_DIR}/check_infrastructure.sh"
echo ""

# Phase 4: Runtime checks — normal operation, degradation, recovery
"${SCRIPTS_DIR}/check_runtime.sh"
echo ""

# Phase 5: Security scans — secrets + dependency CVEs
"${SCRIPTS_DIR}/check_security.sh"
echo ""

echo "================================================================"
echo " All quality gate checks passed."
echo "================================================================"
