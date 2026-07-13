# Milestone 0 — Clean-Clone Verification 2

**Date**: 2026-07-13
**Branch**: `fix/m0-audit-remediation`
**Source-code commit SHA (tested)**: `60016264591711d9daa66f657bd04b0baaf441e3`
**Documentation commit SHA**: recorded after this file is committed (see note below)
**Clone directory**: temporary directory outside the working repository
**Purpose**: Verify end-to-end reproducibility after the CI/local parity correction (shared leaf scripts, Gitleaks binary with checksum, locked installs everywhere).

> **Note on commit SHAs**: The source-code commit (`6001626`) was pushed first and is the commit verified here. This verification document is committed in a separate follow-up commit. The tested SHA is `6001626...`; the doc-only commit SHA is the immediate successor.

---

## Environment

| Tool | Required | Verified |
|---|---|---|
| Operating system | macOS | Darwin 25.3.0 (arm64) |
| Node.js | 24 | v24.18.0 |
| pnpm | 11.12.0 | 11.12.0 |
| Python | 3.12 | 3.12.10 |
| uv | 0.11.7 | 0.11.7 |
| Gitleaks | 8.30.1 | 8.30.1 |
| Docker | present | Docker 29.3.0 |

---

## Procedure and Results

### 1. Clone

```
git clone https://github.com/YashPatel2395/expertseat.git <tmpdir>/expertseat
```

Exit code: **0**

### 2. Checkout branch

```
git checkout fix/m0-audit-remediation
```

Exit code: **0**

### 3. Verify head SHA

```
git rev-parse HEAD
```

Output: `60016264591711d9daa66f657bd04b0baaf441e3`

### 4–5. Verify runtime versions

```
node --version    → v24.18.0
pnpm --version    → 11.12.0
python3 --version → Python 3.12.10
uv --version      → uv 0.11.7
gitleaks version  → 8.30.1
docker --version  → Docker version 29.3.0
```

All version checks passed.

### 6. Copy .env.example to .env

```
cp .env.example .env
```

Exit code: **0**. No credentials in `.env.example`.

### 7. make setup

```
make setup
```

Commands executed:
- `pnpm install --frozen-lockfile` — 459 packages installed, lockfile up to date, exit code 0
- `cd services/api && uv sync --locked --extra dev` — 63 packages installed, exit code 0

Exit code: **0**

### 8. make check

```
make check
```

**Exit code: 0**

| Phase | Result |
|---|---|
| `[versions]` | All version checks and installs passed (Node 24.18.0, pnpm 11.12.0, Python 3.12.10, uv 0.11.7, gitleaks 8.30.1) |
| `[compose]` | Docker Compose configuration valid |
| `[backend]` | ruff format clean, ruff lint clean, pyright 0 errors, pytest **42/42 passed**, API import OK |
| `[frontend]` | prettier clean, eslint clean, tsc clean, vitest **2/2 passed**, next build passed |
| `[infra]` | Docker Compose up, PostgreSQL healthy, Redis healthy, alembic upgrade → downgrade → re-upgrade passed |
| `[runtime]` | Liveness 200, readiness 200, X-Request-ID valid UUID, PostgreSQL degradation 503 + recovery 200, Redis degradation 503 + recovery 200, both-down 503, liveness 200 independent of deps |
| `[secrets]` | gitleaks 8.30.1 version verified, no secrets found in full git history |
| `[dependencies]` | pip-audit: no CVEs; pnpm audit: 1 moderate (no high/critical) |
| `[cleanup]` | Docker Compose stopped, temp files removed |

**Final line**: `All quality gate checks passed.`

### 9. Final git status

```
git status --short
```

Output: *(empty — no tracked files modified)*

---

## Summary

| Check | Result |
|---|---|
| Clone and checkout | Pass |
| Head SHA verified | `60016264591711d9daa66f657bd04b0baaf441e3` |
| pnpm install --frozen-lockfile | Pass |
| uv sync --locked --extra dev | Pass |
| make check (exit code) | **0** |
| pytest | **42 passed, 0 failed** |
| vitest | **2 passed, 0 failed** |
| next build | Pass |
| pyright | 0 errors |
| ruff format + lint | Pass |
| Gitleaks version enforced (8.30.1) | Pass — fails if version mismatches |
| Gitleaks scan | No secrets |
| pip-audit | No CVEs |
| pnpm audit | No high/critical CVEs |
| Migrations (upgrade/downgrade/upgrade) | Pass |
| Runtime degradation and recovery | Pass (all runtime checks) |
| git status --short (clean) | Pass |

---

## What changed since Verification 1

Verification 1 was recorded at `a1320fd`. The following structural changes were introduced in this round and are the subject of this verification:

1. **Six new leaf scripts** (`check_compose.sh`, `check_frontend.sh`, `check_backend.sh`, `check_migrations.sh`, `check_secrets.sh`, `check_dependencies.sh`) — each CI job now calls exactly one repository script.
2. **`check_static.sh`** and **`check_security.sh`** refactored to orchestrate the leaf scripts instead of duplicating commands inline.
3. **`ci.yml`**: `secret-scan` now installs the gitleaks 8.30.1 binary with SHA256 checksum verification from the official release `checksums.txt` (replaces `gitleaks/gitleaks-action`). All six non-runtime jobs call their leaf script. `backend`, `migrations`, and `audit` jobs now use `uv sync --locked --extra dev` (was `--extra dev`).
4. **`check_versions.sh`** and **`check_secrets.sh`** both enforce gitleaks exactly 8.30.1 and fail immediately on version mismatch (was warn-only).
5. **MILESTONE_0_AUDIT.md** section 9 records the defect and the fix.

---

## Notes

- The local postgresql@16 brew service was stopped before running `make check` to free port 5432. This is a pre-condition documented in README.md.
- The `.env` file created during setup contains only development defaults from `.env.example`. It was not committed.
- No personal paths, tokens, credentials, or `.env` contents appear in this document.
