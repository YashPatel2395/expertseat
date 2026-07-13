# Milestone 0 — Clean-Clone Verification

**Date**: 2026-07-13
**Branch**: `fix/m0-audit-remediation`
**Head SHA at verification**: `a1320fd89cdb33126bd02a8addaa0b37d2c658e8`
**Clone directory**: temporary directory outside the working repository
**Purpose**: Prove end-to-end reproducibility from a fresh clone with no pre-existing caches or state.

---

## Environment

| Tool | Required | Verified |
|---|---|---|
| Operating system | macOS | Darwin 25.3.0 (arm64) |
| Node.js | 24 | v24.18.0 |
| pnpm | 11.12.0 | 11.12.0 |
| Python | 3.12 | 3.12.10 |
| uv | 0.11.7 | 0.11.7 |
| Gitleaks | 8.30.1 (reviewed) | 8.30.1 |
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

Output: `a1320fd89cdb33126bd02a8addaa0b37d2c658e8`

### 4–5. Activate pnpm and verify runtime versions

```
corepack enable pnpm
corepack prepare pnpm@11.12.0 --activate
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

Exit code: **0**. No credentials in `.env.example` — values match Docker Compose defaults for local development only.

### 7. make setup

```
make setup
```

Commands executed:
- `pnpm install --frozen-lockfile` — 459 packages installed, lockfile up to date, exit code 0
- `cd services/api && uv sync --locked --extra dev` — 63 packages installed, exit code 0

Exit code: **0**

### 8–9. make check (full 54-step quality gate)

```
make check
```

**Exit code: 0**

Complete output:

| Phase | Steps | Result |
|---|---|---|
| Version checks | 1–6 | All passed (Node 24.18.0, pnpm 11.12.0, Python 3.12.10, uv 0.11.7, Gitleaks 8.30.1) |
| Static analysis | 7–17 | All passed (ruff format, ruff lint, pyright, prettier, eslint, tsc, pytest 42/42, vitest 2/2, next build, import check) |
| Infrastructure | 18–23 | All passed (Docker Compose up, PostgreSQL healthy, Redis healthy, alembic upgrade, downgrade, re-upgrade) |
| Runtime | 24–47 | All passed (liveness 200, exact body `{"status":"ok"}`, readiness 200, both deps healthy, valid UUID X-Request-ID, PostgreSQL degradation 503, recovery 200, Redis degradation 503, recovery 200, both-down 503, liveness 200 independent of deps) |
| Security | 48–50 | All passed (Gitleaks: no secrets, pip-audit: no CVEs, pnpm audit: no high/critical CVEs) |
| Cleanup | 51–54 | Completed |

**make check final line**: `All quality gate checks passed.`

### 10–12. Start infrastructure and development servers

```
docker compose -f infrastructure/docker-compose.yml up -d
# Waited for PostgreSQL and Redis healthy
cd services/api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 &
cd apps/web && pnpm dev &
```

Both servers started successfully.

### 13–15. Verify endpoints

| Endpoint | HTTP status | Response body |
|---|---|---|
| `http://127.0.0.1:3000` (Next.js frontend) | **200** | HTML (ExpertSeat page) |
| `http://127.0.0.1:8000/api/v1/health/live` | **200** | `{"status":"ok"}` |
| `http://127.0.0.1:8000/api/v1/health/ready` | **200** | `{"status":"ready","checks":{"database":"ok","redis":"ok"}}` |

### 16–19. Stop servers and infrastructure

```
kill <uvicorn-pid>       → stopped
kill <nextjs-pid>        → stopped
docker compose -f infrastructure/docker-compose.yml down
```

```
docker ps --filter name=infrastructure
→ CONTAINER ID   IMAGE   COMMAND   CREATED   STATUS   PORTS   NAMES
  (empty — no containers running)
```

No orphaned ExpertSeat containers. No orphaned Uvicorn or Next.js processes from this clone.

### 20–21. Final git status

```
git status --short
```

Output: *(empty — no tracked files modified)*

The `.env` file created by `cp .env.example .env` is in `.gitignore` and does not appear in `git status`.

---

## Summary

| Check | Result |
|---|---|
| Clone and checkout | Pass |
| Head SHA verified | `a1320fd89cdb33126bd02a8addaa0b37d2c658e8` |
| pnpm install --frozen-lockfile | Pass |
| uv sync --locked --extra dev | Pass |
| make check (exit code) | **0** |
| pytest | **42 passed, 0 failed** |
| vitest | **2 passed, 0 failed** |
| next build | Pass |
| pyright | 0 errors |
| ruff format + lint | Pass |
| Gitleaks | No secrets |
| pip-audit | No CVEs |
| pnpm audit | No high/critical CVEs |
| Migrations (upgrade/downgrade/upgrade) | Pass |
| Runtime degradation and recovery | Pass (all 24 runtime checks) |
| Frontend HTTP 200 | Pass |
| API liveness HTTP 200 + body | Pass |
| API readiness HTTP 200 + body | Pass |
| No orphaned containers | Pass |
| No orphaned processes | Pass |
| git status --short (clean) | Pass |

---

## Notes

- The local PostgreSQL service (`postgresql@16`, brew-managed) was stopped before running `make check` to free port 5432. This is a pre-condition documented in README.md: "Docker and Docker Compose — required for `make check` and local infrastructure."
- The clone used HTTPS (public repository, no authentication required).
- The `.env` file created during setup contains only development defaults from `.env.example`. It was not committed.
- No personal paths, tokens, credentials, or `.env` contents are included in this document.
