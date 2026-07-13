#!/usr/bin/env bash
# check_security.sh — Security scans: Gitleaks (secrets), pip-audit (Python CVEs),
# pnpm audit (npm CVEs). These are distinct scans with different purposes:
#   - Gitleaks: detects accidentally committed credentials and API keys in git history
#   - pip-audit: detects known CVEs in Python package dependencies
#   - pnpm audit: detects known CVEs in npm package dependencies
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${REPO_ROOT}/services/api"

echo "=== [security] Security scans ==="

echo "  [48] Gitleaks — full git history secret scan"
if command -v gitleaks >/dev/null 2>&1; then
  GL_VER=$(gitleaks version 2>&1 | awk '{print $1}')
  echo "  gitleaks version: ${GL_VER} (reviewed: 8.30.1)"
  gitleaks detect --source "${REPO_ROOT}" --log-level warn
  echo "  Gitleaks: no secrets found ✓"
else
  echo "ERROR: gitleaks is not installed."
  echo "  Install: brew install gitleaks"
  exit 1
fi

echo "  [49] pip-audit — Python dependency CVE scan"
cd "${API_DIR}"
uv run pip-audit
echo "  pip-audit: no known CVEs ✓"

echo "  [50] pnpm audit — npm dependency CVE scan (high and critical)"
cd "${REPO_ROOT}"
pnpm audit --audit-level high
echo "  pnpm audit: no high/critical CVEs ✓"

echo "=== [security] All security scans passed ==="
