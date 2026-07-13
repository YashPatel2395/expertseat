#!/usr/bin/env bash
# check_secrets.sh — Verify Gitleaks is exactly 8.30.1 and scan full git history for secrets.
# Used by: check_security.sh (local), CI secret-scan job.
# Fails if Gitleaks is absent, if the version does not match, or if any secret is found.
set -euo pipefail

REQUIRED_GITLEAKS="8.30.1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== [secrets] Gitleaks secret scan ==="

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "ERROR: gitleaks is not installed."
  echo "  Install the required version: brew install gitleaks"
  exit 1
fi

GL_VER=$(gitleaks version 2>&1 | awk '{print $1}')
echo "  gitleaks version: ${GL_VER} (required: ${REQUIRED_GITLEAKS})"
if [ "${GL_VER}" != "${REQUIRED_GITLEAKS}" ]; then
  echo "ERROR: gitleaks ${REQUIRED_GITLEAKS} required, got ${GL_VER}."
  echo "  Update to the required version: brew install gitleaks"
  exit 1
fi

echo "  Scanning full git history..."
gitleaks detect --source "${REPO_ROOT}" --log-level warn

echo "  Gitleaks: no secrets found"
echo "=== [secrets] Secret scan passed ==="
