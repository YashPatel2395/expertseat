#!/usr/bin/env bash
# check_runtime.sh — API runtime checks: HTTP smoke tests, degradation and recovery.
#
# Prerequisites: check_infrastructure.sh has already started Docker services and
# run migrations (services must be healthy before this script runs).
#
# Starts Uvicorn as a background process; cleanup trap stops it on exit.
# Stops/restarts individual Docker services to verify degradation and recovery.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${REPO_ROOT}/services/api"
COMPOSE="docker compose -f ${REPO_ROOT}/infrastructure/docker-compose.yml"
API_PORT="${API_PORT:-8000}"
API_HOST="127.0.0.1"
BASE_URL="http://${API_HOST}:${API_PORT}/api/v1/health"
LIVENESS_TIMEOUT="${LIVENESS_TIMEOUT:-15}"
INFRA_TIMEOUT="${INFRA_TIMEOUT:-60}"
UVICORN_PID_FILE="/tmp/expertseat-uvicorn.pid"

# Load .env for DATABASE_URL / REDIS_URL if not set in environment
if [ -z "${DATABASE_URL:-}" ] && [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/.env"
  set +a
fi

cleanup_uvicorn() {
  if [ -f "${UVICORN_PID_FILE}" ]; then
    PID=$(cat "${UVICORN_PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
      kill "${PID}" 2>/dev/null || true
      echo "  Uvicorn (PID ${PID}) stopped."
    fi
    rm -f "${UVICORN_PID_FILE}"
  fi
}
trap cleanup_uvicorn EXIT

# ─── Helper functions ─────────────────────────────────────────────────────────

http_status() {
  curl -s -o /dev/null -w "%{http_code}" "${1}"
}

http_body() {
  curl -s "${1}"
}

assert_status() {
  local URL="${1}" EXPECTED="${2}" LABEL="${3}"
  local ACTUAL
  ACTUAL=$(http_status "${URL}")
  [ "${ACTUAL}" = "${EXPECTED}" ] \
    || { echo "ERROR [${LABEL}]: expected HTTP ${EXPECTED}, got ${ACTUAL}"; exit 1; }
  echo "  ${LABEL}: HTTP ${ACTUAL} ✓"
}

assert_json_field() {
  local BODY="${1}" FIELD="${2}" EXPECTED="${3}" LABEL="${4}"
  local ACTUAL
  ACTUAL=$(echo "${BODY}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d${FIELD})" 2>/dev/null || echo "__parse_error__")
  [ "${ACTUAL}" = "${EXPECTED}" ] \
    || { echo "ERROR [${LABEL}]: expected ${FIELD}==${EXPECTED}, got '${ACTUAL}'"; echo "  Body: ${BODY}"; exit 1; }
  echo "  ${LABEL}: ${FIELD}==${EXPECTED} ✓"
}

wait_for_status() {
  local URL="${1}" EXPECTED="${2}" TIMEOUT="${3}" LABEL="${4}"
  local DEADLINE
  DEADLINE=$(( $(date +%s) + TIMEOUT ))
  while true; do
    local STATUS
    STATUS=$(http_status "${URL}")
    [ "${STATUS}" = "${EXPECTED}" ] && { echo "  ${LABEL}: HTTP ${EXPECTED} ✓"; return 0; }
    [ "$(date +%s)" -lt "${DEADLINE}" ] \
      || { echo "ERROR [${LABEL}]: timed out waiting for HTTP ${EXPECTED} (last: ${STATUS})"; exit 1; }
    sleep 1
  done
}

wait_postgres_healthy() {
  local TIMEOUT="${1:-${INFRA_TIMEOUT}}" LABEL="${2:-postgres}"
  local DEADLINE
  DEADLINE=$(( $(date +%s) + TIMEOUT ))
  until docker inspect --format='{{.State.Health.Status}}' \
      $(${COMPOSE} ps -q postgres) 2>/dev/null | grep -q "^healthy$"; do
    [ "$(date +%s)" -lt "${DEADLINE}" ] \
      || { echo "ERROR [${LABEL}]: PostgreSQL did not recover within ${TIMEOUT}s"; exit 1; }
    sleep 1
  done
  echo "  ${LABEL}: healthy ✓"
}

wait_redis_healthy() {
  local TIMEOUT="${1:-${INFRA_TIMEOUT}}" LABEL="${2:-redis}"
  local DEADLINE
  DEADLINE=$(( $(date +%s) + TIMEOUT ))
  until docker inspect --format='{{.State.Health.Status}}' \
      $(${COMPOSE} ps -q redis) 2>/dev/null | grep -q "^healthy$"; do
    [ "$(date +%s)" -lt "${DEADLINE}" ] \
      || { echo "ERROR [${LABEL}]: Redis did not recover within ${TIMEOUT}s"; exit 1; }
    sleep 1
  done
  echo "  ${LABEL}: healthy ✓"
}

# ─── Start Uvicorn ────────────────────────────────────────────────────────────

echo "=== [runtime] Starting Uvicorn ==="
cd "${API_DIR}"
uv run uvicorn app.main:app --host "${API_HOST}" --port "${API_PORT}" \
  > /tmp/expertseat-uvicorn.log 2>&1 &
UVICORN_PID=$!
echo "${UVICORN_PID}" > "${UVICORN_PID_FILE}"
echo "  Uvicorn started (PID ${UVICORN_PID})"

# ─── Wait for liveness ────────────────────────────────────────────────────────

echo "  Waiting for liveness (timeout: ${LIVENESS_TIMEOUT}s)..."
DEADLINE=$(( $(date +%s) + LIVENESS_TIMEOUT ))
while true; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/live" 2>/dev/null || echo "000")
  [ "${STATUS}" = "200" ] && break
  [ "$(date +%s)" -lt "${DEADLINE}" ] \
    || { echo "ERROR: Uvicorn did not start within ${LIVENESS_TIMEOUT}s"; cat /tmp/expertseat-uvicorn.log; exit 1; }
  sleep 0.5
done
echo "  Uvicorn ready."

# ─── Normal operation checks ─────────────────────────────────────────────────

echo "=== [runtime] Normal operation ==="

echo "  [24] Liveness — HTTP 200"
assert_status "${BASE_URL}/live" "200" "liveness"

echo "  [25/26] Liveness — exact JSON body"
LIVE_BODY=$(http_body "${BASE_URL}/live")
[ "${LIVE_BODY}" = '{"status":"ok"}' ] \
  || { echo "ERROR: liveness body: '${LIVE_BODY}'"; exit 1; }
echo "  liveness body: ${LIVE_BODY} ✓"

echo "  [27] Readiness — HTTP 200"
assert_status "${BASE_URL}/ready" "200" "readiness"

echo "  [28] Readiness — both deps healthy"
READY_BODY=$(http_body "${BASE_URL}/ready")
assert_json_field "${READY_BODY}" "['status']" "ready" "readiness.status"
assert_json_field "${READY_BODY}" "['checks']['database']" "ok" "readiness.database"
assert_json_field "${READY_BODY}" "['checks']['redis']" "ok" "readiness.redis"

echo "  [29] X-Request-ID present and valid UUID"
REQUEST_ID=$(curl -s -I "${BASE_URL}/live" \
  | grep -i "^x-request-id:" | tr -d '[:space:]\r' | sed 's/^x-request-id://i')
echo "  X-Request-ID: ${REQUEST_ID}"
[ -n "${REQUEST_ID}" ] || { echo "ERROR: X-Request-ID header missing"; exit 1; }
echo "${REQUEST_ID}" \
  | grep -qE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' \
  || { echo "ERROR: X-Request-ID is not a valid UUID: '${REQUEST_ID}'"; exit 1; }
echo "  X-Request-ID is valid UUID ✓"

# ─── PostgreSQL degradation and recovery ─────────────────────────────────────

echo "=== [runtime] PostgreSQL degradation ==="

echo "  [30] Stopping PostgreSQL..."
${COMPOSE} stop postgres

echo "  [31] Waiting for readiness to return 503..."
wait_for_status "${BASE_URL}/ready" "503" 20 "readiness after postgres stop"

echo "  [32] Verifying database unavailable in response body"
BODY=$(http_body "${BASE_URL}/ready")
assert_json_field "${BODY}" "['checks']['database']" "unavailable" "database unavailable"

echo "  [33] Verifying Redis still healthy in response body"
assert_json_field "${BODY}" "['checks']['redis']" "ok" "redis still healthy"

echo "  [34] Restarting PostgreSQL..."
${COMPOSE} start postgres

echo "  [35] Waiting for PostgreSQL to become healthy..."
wait_postgres_healthy "${INFRA_TIMEOUT}" "postgres recovery"

echo "  [36] Verifying readiness recovers to HTTP 200..."
wait_for_status "${BASE_URL}/ready" "200" 30 "readiness recovery after postgres restart"

# ─── Redis degradation and recovery ──────────────────────────────────────────

echo "=== [runtime] Redis degradation ==="

echo "  [37] Stopping Redis..."
${COMPOSE} stop redis

echo "  [38] Waiting for readiness to return 503..."
wait_for_status "${BASE_URL}/ready" "503" 20 "readiness after redis stop"

echo "  [39] Verifying Redis unavailable in response body"
BODY=$(http_body "${BASE_URL}/ready")
assert_json_field "${BODY}" "['checks']['redis']" "unavailable" "redis unavailable"

echo "  [40] Verifying database still healthy in response body"
assert_json_field "${BODY}" "['checks']['database']" "ok" "database still healthy"

echo "  [41] Restarting Redis..."
${COMPOSE} start redis

echo "  [42] Waiting for Redis to become healthy..."
wait_redis_healthy "${INFRA_TIMEOUT}" "redis recovery"

echo "  [43] Verifying readiness recovers to HTTP 200..."
wait_for_status "${BASE_URL}/ready" "200" 30 "readiness recovery after redis restart"

# ─── Both dependencies down ───────────────────────────────────────────────────

echo "=== [runtime] Both dependencies down ==="

echo "  [44] Stopping PostgreSQL and Redis..."
${COMPOSE} stop postgres redis

echo "  [45] Waiting for readiness to return 503..."
wait_for_status "${BASE_URL}/ready" "503" 20 "readiness with both deps down"

echo "  [46] Verifying both deps reported unavailable"
BODY=$(http_body "${BASE_URL}/ready")
assert_json_field "${BODY}" "['checks']['database']" "unavailable" "database unavailable (both down)"
assert_json_field "${BODY}" "['checks']['redis']" "unavailable" "redis unavailable (both down)"

echo "  [47] Verifying liveness still returns 200 (independent of deps)"
assert_status "${BASE_URL}/live" "200" "liveness independent of deps"

echo "  Restarting both services for clean exit..."
${COMPOSE} start postgres redis 2>/dev/null || true

echo "=== [runtime] All runtime checks passed ==="
