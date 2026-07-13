# Milestone 0 — Clean-Clone Verification

**Date**: 2026-07-13
**Branch**: `fix/m0-audit-remediation`
**Purpose**: Prove that the repository works end-to-end from a clean clone with no pre-existing caches, virtual environments, or node_modules.

---

## Procedure

The following steps were run in a fresh temporary directory with no prior state.

### 1. Clone

```bash
git clone git@github.com:YashPatel2395/expertseat.git
cd expertseat
git checkout fix/m0-audit-remediation
```

### 2. Install dependencies (no cache)

```bash
corepack enable pnpm
corepack prepare pnpm@11.12.0 --activate
pnpm install --frozen-lockfile
cd services/api && uv sync --extra dev && cd ../..
```

### 3. Backend static analysis

```bash
cd services/api
uv run ruff format --check .        # exit 0
uv run ruff check .                  # exit 0
uv run pyright                       # exit 0
uv run pytest -v                     # 36 passed
cd ../..
```

### 4. Frontend static analysis and build

```bash
pnpm run --filter web format:check  # exit 0
pnpm run --filter web lint          # exit 0
pnpm run --filter web typecheck     # exit 0
pnpm run --filter web test          # 2 passed
pnpm run --filter web build         # exit 0
```

### 5. Infrastructure

```bash
docker compose -f infrastructure/docker-compose.yml config --quiet  # exit 0
docker compose -f infrastructure/docker-compose.yml up -d
# Wait for PostgreSQL and Redis healthy
cd services/api
uv run alembic upgrade head          # exit 0
uv run alembic downgrade base        # exit 0
uv run alembic upgrade head          # exit 0
cd ../..
```

### 6. Runtime smoke test

```bash
cd services/api
APP_ENV=development uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 &
sleep 3
curl -s http://127.0.0.1:8000/api/v1/health/live   # {"status":"ok"}
curl -s http://127.0.0.1:8000/api/v1/health/ready  # {"status":"ready","checks":{"database":"ok","redis":"ok"}}
kill %1
cd ../..
```

### 7. Security scan

```bash
gitleaks detect --source . --log-level warn          # No leaks found
cd services/api && uv run pip-audit && cd ../..      # No known vulnerabilities
pnpm audit --audit-level high                        # No high or critical vulnerabilities
```

---

## Results

| Step | Result |
|---|---|
| Clone and checkout | Pass |
| pnpm install --frozen-lockfile | Pass |
| uv sync --extra dev | Pass |
| ruff format --check | Pass |
| ruff check | Pass |
| pyright | Pass |
| pytest (36 tests) | Pass — 36 passed, 0 failed |
| pnpm format:check | Pass |
| pnpm lint | Pass |
| pnpm typecheck | Pass |
| pnpm test (2 tests) | Pass — 2 passed, 0 failed |
| pnpm build | Pass |
| docker compose config | Pass |
| alembic upgrade/downgrade/upgrade | Pass |
| liveness endpoint | Pass — HTTP 200, body `{"status":"ok"}` |
| readiness endpoint | Pass — HTTP 200, both checks ok |
| Gitleaks | Pass — no secrets found |
| pip-audit | Pass — no Python CVEs |
| pnpm audit | Pass — no high/critical npm CVEs |

---

## Notes

- Verification was run on macOS Darwin 25.3.0 (arm64)
- Node.js version: 24 LTS (verified via `node --version`)
- pnpm version: 11.12.0 (verified via `pnpm --version`)
- Python version: 3.12 (verified via `python --version`)
- uv version: 0.11.7+ (verified via `uv --version`)
- Docker Desktop running with Docker Compose plugin
- No `.env` file was created before running (tested that defaults work for local dev)

---

## CI Equivalence

The `make check` command (`scripts/check_all.sh`) runs the same 54 steps that CI runs. The clean-clone verification above exercises the same phases. CI additionally:
- Runs in an isolated Ubuntu runner with no cached state
- Uses the same Docker Compose (not GitHub Actions `services:`) so containers can be stopped and restarted for degradation tests
- Tests PostgreSQL degradation, Redis degradation, and both-down scenarios

The local `make check` gate is equivalent to CI for development purposes. CI is the authoritative gate for merge readiness.
