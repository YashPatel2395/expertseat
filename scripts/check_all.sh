#!/usr/bin/env bash
# check_all.sh — Complete 54-step quality gate for ExpertSeat.
#
# Runs all validation phases in order:
#   1. Version checks and dependency installation
#   2. Static analysis (format, lint, typecheck, tests, build)
#   3. Infrastructure startup and database migration cycle
#   4. API runtime verification (liveness, readiness, degradation, recovery)
#   5. Security scans (secrets, CVEs)
#   6. Cleanup
#
# Must be run from the repository root or from scripts/.
# Requires: Docker, Node.js 24, pnpm 11.12.0, Python 3.12, uv 0.11.7, gitleaks.
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
echo " ExpertSeat — complete quality gate (54 steps)"
echo "================================================================"
echo ""

# Phase 1: Version checks and dependency installation (steps 1–6)
"${SCRIPTS_DIR}/check_versions.sh"
echo ""

# Phase 2: Static validation (steps 7–17)
"${SCRIPTS_DIR}/check_static.sh"
echo ""

# Phase 3: Infrastructure and migrations (steps 18–23)
# CLEANUP_INFRA=false so services remain running for check_runtime.sh
CLEANUP_INFRA=false "${SCRIPTS_DIR}/check_infrastructure.sh"
echo ""

# Phase 4: Runtime checks — normal operation, degradation, recovery (steps 24–47)
"${SCRIPTS_DIR}/check_runtime.sh"
echo ""

# Phase 5: Security scans (steps 48–50)
"${SCRIPTS_DIR}/check_security.sh"
echo ""

echo "================================================================"
echo " All quality gate checks passed."
echo "================================================================"
