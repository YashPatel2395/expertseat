#!/usr/bin/env bash
# check_compose.sh — Validate Docker Compose configuration (no services started).
# Used by: check_static.sh (local), CI infra-validate job.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== [compose] Docker Compose validation ==="
docker compose -f "${REPO_ROOT}/infrastructure/docker-compose.yml" config --quiet
echo "=== [compose] Docker Compose configuration valid ==="
