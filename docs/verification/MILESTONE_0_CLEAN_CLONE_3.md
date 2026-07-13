# Milestone 0 — Clean-Clone Verification 3

**Date**: 2026-07-13
**Branch**: `fix/m0-audit-remediation`
**Source-code commit SHA (tested)**: `8ac66da4ac88c57d7f47b01bee8262a433469490`
**Documentation commit SHA**: committed immediately after this file (see note below)
**Clone directory**: temporary directory outside the working repository
**Purpose**: Verify end-to-end reproducibility after the migration parity finalization — `check_infrastructure.sh` delegates to `check_migrations.sh` as the sole migration-cycle owner.

> **Note on commit SHAs**: The source-code commit (`8ac66da`) was pushed first and is the commit verified here. This verification document is committed in a separate follow-up commit. The tested SHA is `8ac66da...`; the doc-only commit SHA is the immediate successor.

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

Output: `8ac66da4ac88c57d7f47b01bee8262a433469490`

### 4. Verify runtime versions

```
node --version    → v24.18.0
pnpm --version    → 11.12.0
python3 --version → Python 3.12.10
uv --version      → uv 0.11.7
gitleaks version  → 8.30.1
docker --version  → Docker version 29.3.0
```

All version checks passed.

### 5. Copy .env.example to .env

```
cp .env.example .env
```

Exit code: **0**

### 6. make setup

```
make setup
```

- `pnpm install --frozen-lockfile` — 459 packages, exit code 0
- `uv sync --locked --extra dev` — 63 packages, exit code 0

Exit code: **0**

### 7. make check

```
make check
```

**Exit code: 0**

| Phase | Result |
|---|---|
| `[versions]` | All version checks passed (Node 24.18.0, pnpm 11.12.0, Python 3.12.10, uv 0.11.7, gitleaks 8.30.1) |
| `[compose]` | Docker Compose configuration valid |
| `[backend]` | ruff format clean, ruff lint clean, pyright 0 errors, pytest **42/42 passed**, API import OK |
| `[frontend]` | prettier clean, eslint clean, tsc clean, vitest **2/2 passed**, next build passed |
| `[infra]` | Docker Compose up, PostgreSQL healthy, Redis healthy |
| `[migrations]` | uv sync locked, alembic upgrade → downgrade → re-upgrade — **Migration cycle passed** |
| `[infra]` | **Infrastructure and migrations passed** (confirming check_infrastructure.sh delegated to check_migrations.sh) |
| `[runtime]` | Liveness 200, readiness 200, X-Request-ID valid UUID, PostgreSQL degradation 503 + recovery 200, Redis degradation 503 + recovery 200, both-down 503, liveness 200 independent of deps |
| `[secrets]` | gitleaks 8.30.1 version verified, no secrets found |
| `[dependencies]` | pip-audit: no CVEs; pnpm audit: 1 moderate (no high/critical) |
| `[cleanup]` | Docker Compose stopped, temp files removed |

**Final line**: `All quality gate checks passed.`

The output sequence `=== [migrations] Migration cycle passed ===` followed by `=== [infra] Infrastructure and migrations passed ===` confirms that `check_infrastructure.sh` delegates migration execution to `check_migrations.sh`.

### 8. Migration single source of truth verification

```
grep -R "alembic upgrade\|alembic downgrade" scripts .github Makefile
```

Results:
- `scripts/check_migrations.sh` — 3 executable invocations (`uv run alembic upgrade head`, `uv run alembic downgrade base`, `uv run alembic upgrade head`) plus 1 comment line
- `scripts/check_all.sh` — 1 comment line only (no executable command)
- `scripts/check_infrastructure.sh` — 1 comment line only (no executable command)
- `Makefile` — 2 developer convenience targets (`make migrate`, `make migrate-down`); not part of the validation path (`make check`)
- `.github/` — no matches

**Executable migration-cycle validation logic exists only in `scripts/check_migrations.sh`.**

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
| Head SHA verified | `8ac66da4ac88c57d7f47b01bee8262a433469490` |
| pnpm install --frozen-lockfile | Pass |
| uv sync --locked --extra dev | Pass |
| make check (exit code) | **0** |
| pytest | **42 passed, 0 failed** |
| vitest | **2 passed, 0 failed** |
| next build | Pass |
| pyright | 0 errors |
| ruff format + lint | Pass |
| Gitleaks version enforced (8.30.1) | Pass |
| Gitleaks scan | No secrets |
| pip-audit | No CVEs |
| pnpm audit | No high/critical CVEs |
| Migration cycle (upgrade/downgrade/upgrade) | Pass — executed by check_migrations.sh |
| check_infrastructure.sh → check_migrations.sh delegation | Confirmed from output |
| Migration commands in scripts other than check_migrations.sh | None (executable) |
| Runtime degradation and recovery | Pass (all runtime checks) |
| git status --short (clean) | Pass |

---

## What changed since Verification 2

Verification 2 was at `6001626`. This verification is at `8ac66da`.

`check_infrastructure.sh` previously contained its own inline Alembic cycle (upgrade → downgrade → upgrade), duplicating the logic in `check_migrations.sh`. The full migration cycle now exists only in `check_migrations.sh`. `check_infrastructure.sh` delegates to it after services are healthy.

Delegation chain after this fix:
```
make check → check_all.sh → check_infrastructure.sh → check_migrations.sh
CI runtime                → check_infrastructure.sh → check_migrations.sh
CI migrations job                                   → check_migrations.sh (direct)
```

---

## Notes

- The local postgresql@16 brew service was stopped before running `make check` to free port 5432.
- The `.env` file created during setup contains only development defaults. It was not committed.
- No personal paths, tokens, credentials, or `.env` contents appear in this document.
