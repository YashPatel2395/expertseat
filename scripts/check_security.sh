#!/usr/bin/env bash
# check_security.sh — Security scan orchestrator.
# Delegates to leaf scripts so that local and CI share the same validation logic.
#
# Leaf scripts called:
#   check_secrets.sh      — Gitleaks 8.30.1 full history scan (fails on version mismatch)
#   check_dependencies.sh — pip-audit (Python CVEs) + pnpm audit (npm CVEs)
#
# Note: secrets scanning and dependency CVE scanning are separate concerns.
#   Gitleaks detects accidentally committed credentials in git history.
#   pip-audit and pnpm audit detect known CVEs in third-party packages.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== [security] Security scans ==="

"${SCRIPTS_DIR}/check_secrets.sh"
"${SCRIPTS_DIR}/check_dependencies.sh"

echo "=== [security] All security scans passed ==="
