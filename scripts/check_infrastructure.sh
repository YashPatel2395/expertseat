#!/usr/bin/env bash
# check_infrastructure.sh — Start Docker Compose services, wait for health, run migrations.
#
# Starts PostgreSQL and Redis, waits for both to become healthy, then delegates
# the full migration cycle to scripts/check_migrations.sh (the single source of
# truth for: uv sync --locked --extra dev, alembic upgrade, downgrade, re-upgrade).
#
# By default (CLEANUP_INFRA=true) stops services on exit so the script is safe
# to run standalone. When invoked from check_all.sh, CLEANUP_INFRA=false is set
# so services remain running for check_runtime.sh.
#
# Callers:
#   check_all.sh (local make check) — CLEANUP_INFRA=false
#   CI runtime job                  — CLEANUP_INFRA=false
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPTS_DIR}/.." && pwd)"
COMPOSE="docker compose -f ${REPO_ROOT}/infrastructure/docker-compose.yml"
INFRA_TIMEOUT="${INFRA_TIMEOUT:-60}"
CLEANUP_INFRA="${CLEANUP_INFRA:-true}"

# Load .env for DATABASE_URL / REDIS_URL if not set in environment
if [ -z "${DATABASE_URL:-}" ] && [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/.env"
  set +a
fi

cleanup() {
  if [ "${CLEANUP_INFRA}" = "true" ]; then
    echo "--- [infra] Stopping Docker Compose services ---"
    ${COMPOSE} down --volumes 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "=== [infra] Starting Docker Compose services ==="
${COMPOSE} up -d

echo "  Waiting for PostgreSQL (timeout: ${INFRA_TIMEOUT}s)..."
DEADLINE=$(( $(date +%s) + INFRA_TIMEOUT ))
while true; do
  STATUS=$(docker inspect --format='{{.State.Health.Status}}' \
    $(${COMPOSE} ps -q postgres) 2>/dev/null || echo "missing")
  [ "${STATUS}" = "healthy" ] && break
  [ "$(date +%s)" -lt "${DEADLINE}" ] \
    || { echo "ERROR: PostgreSQL did not become healthy within ${INFRA_TIMEOUT}s"; exit 1; }
  sleep 1
done
echo "  PostgreSQL healthy."

echo "  Waiting for Redis (timeout: ${INFRA_TIMEOUT}s)..."
DEADLINE=$(( $(date +%s) + INFRA_TIMEOUT ))
while true; do
  STATUS=$(docker inspect --format='{{.State.Health.Status}}' \
    $(${COMPOSE} ps -q redis) 2>/dev/null || echo "missing")
  [ "${STATUS}" = "healthy" ] && break
  [ "$(date +%s)" -lt "${DEADLINE}" ] \
    || { echo "ERROR: Redis did not become healthy within ${INFRA_TIMEOUT}s"; exit 1; }
  sleep 1
done
echo "  Redis healthy."

# Delegate migration cycle to the single source of truth.
# DATABASE_URL exported above is inherited by check_migrations.sh.
"${SCRIPTS_DIR}/check_migrations.sh"

echo "=== [infra] Infrastructure and migrations passed ==="
