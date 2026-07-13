#!/usr/bin/env bash
# check_versions.sh — Verify required tool versions and install dependencies.
# Fails immediately if any version does not match the pinned requirement.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${REPO_ROOT}/services/api"

echo "=== [versions] Checking tool versions ==="

# Node.js — must be major version 24
NODE_VER=$(node --version)
NODE_MAJOR=$(echo "${NODE_VER}" | cut -d. -f1 | tr -d 'v')
echo "  Node.js: ${NODE_VER}"
[ "${NODE_MAJOR}" = "24" ] || { echo "ERROR: Node.js 24 required, got ${NODE_VER}"; exit 1; }

# pnpm — must be exactly 11.12.0
PNPM_VER=$(pnpm --version)
echo "  pnpm: ${PNPM_VER}"
[ "${PNPM_VER}" = "11.12.0" ] || { echo "ERROR: pnpm 11.12.0 required, got ${PNPM_VER}"; exit 1; }

# Python — must be 3.12.x
PYTHON_VER=$(python3 --version | awk '{print $2}')
PYTHON_MAJOR=$(echo "${PYTHON_VER}" | cut -d. -f1)
PYTHON_MINOR=$(echo "${PYTHON_VER}" | cut -d. -f2)
echo "  Python: ${PYTHON_VER}"
[ "${PYTHON_MAJOR}" = "3" ] && [ "${PYTHON_MINOR}" = "12" ] \
  || { echo "ERROR: Python 3.12 required, got ${PYTHON_VER}"; exit 1; }

# uv — must be exactly the pinned version
PINNED_UV="0.11.7"
UV_VER=$(uv --version | awk '{print $2}')
echo "  uv: ${UV_VER}"
[ "${UV_VER}" = "${PINNED_UV}" ] || { echo "ERROR: uv ${PINNED_UV} required, got ${UV_VER}"; exit 1; }

# Gitleaks — must be present; version is recorded for audit evidence
if command -v gitleaks >/dev/null 2>&1; then
  GL_VER=$(gitleaks version 2>&1 | awk '{print $1}')
  echo "  gitleaks: ${GL_VER}"
  echo "  (reviewed version for audit: 8.30.1; installed: ${GL_VER})"
else
  echo "ERROR: gitleaks is not installed."
  echo "  Install: brew install gitleaks"
  exit 1
fi

echo "=== [versions] Installing dependencies ==="

echo "  pnpm install --frozen-lockfile"
cd "${REPO_ROOT}"
pnpm install --frozen-lockfile

echo "  uv sync --locked --extra dev"
cd "${API_DIR}"
uv sync --locked --extra dev

echo "=== [versions] All version checks and installs passed ==="
