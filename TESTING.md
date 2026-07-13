# ExpertSeat — Testing Strategy

**Status**: Milestone 0 — Foundation (updated 2026-07-13)
**Date**: 2026-07-13

---

## Philosophy

- Tests are first-class code. They live next to the code they test and are maintained with the same care.
- All tests must pass before merging to `main`.
- Tests document behavior — they explain what the system does, not just check that it doesn't crash.
- We prefer fast, deterministic unit tests. Slow tests should be few and isolated.
- We do not test implementation details. We test behavior and contracts.

---

## Test Layers

### Unit Tests

Fast, isolated tests of pure logic. No database, no network, no filesystem.

- **Backend**: `services/api/tests/` — pytest, mocks for database and Redis
- **Frontend**: `apps/web/src/**/__tests__/` — vitest + @testing-library/react

These run on every push and PR. Target: < 30 seconds total.

### API / Integration Tests

Tests that exercise multiple layers together (router → service → database). Require a running test database.

- **Backend**: marked with `pytest.mark.integration` (not yet implemented — planned Milestone 1)
- Run in CI with a PostgreSQL service container

### Migration Tests

Tests that verify database migrations can be applied and rolled back cleanly.

- Apply all migrations from scratch (`alembic upgrade head`)
- Roll back all migrations (`alembic downgrade base`)
- Re-apply all migrations (`alembic upgrade head`)
- This full cycle runs in CI as the `migrations` job
- Currently: one no-op placeholder migration. Real schema tests begin Milestone 1.

### Component Tests (Frontend)

Tests that render React components in isolation with realistic props and interactions.

- Tool: vitest + @testing-library/react
- Currently only covering the `Home` page component
- Will expand as components are built (Milestone 1+)

### End-to-End Tests (Planned, Milestone 4)

Tests that simulate real user workflows through the browser.

- Tool: Playwright
- Will be added in Milestone 4 when there are real end-to-end interview flows to test
- Run in CI on merge to `main` only (not on every push, as they are slow)

### AI Evaluation Tests (Planned, Milestone 4)

Tests that evaluate Role Agent output quality.

- Tool: custom evaluation harness (TBD)
- Verify that agent questions are grounded in provided evidence
- Verify that agent does not hallucinate facts
- These are probabilistic and require a defined threshold, not a binary pass/fail
- Architecture for these tests is TBD

### Runtime Smoke Tests

Tests that start the actual Uvicorn server and make real HTTP requests. These verify that:
- The application starts without import errors or configuration failures
- Health endpoints respond with correct HTTP status codes and exact JSON bodies
- The readiness endpoint correctly reflects dependency health
- The `X-Request-ID` response header is present and is a valid UUID on every response
- The readiness endpoint returns 503 (degraded) when a dependency is unavailable
- The readiness endpoint recovers to 200 when a dependency is restored
- Graceful degradation: when PostgreSQL is stopped, readiness returns `database: unavailable` but `redis: ok`; when Redis is stopped, readiness returns `redis: unavailable` but `database: ok`; liveness always returns 200 regardless of dependency state

These run in CI as the `runtime` job. The job uses Docker Compose (not GitHub Actions `services:`) so that individual containers can be stopped and restarted to test degradation and recovery. The job delegates to `scripts/check_infrastructure.sh` (migration cycle) and `scripts/check_runtime.sh` (HTTP verification and degradation tests).

### Evidence Integrity Tests (Planned, Milestone 5)

Tests that verify "no evidence, no score" enforcement:
- Observations without evidence citations are flagged, not scored
- "Insufficient evidence" is returned explicitly when evidence is below threshold
- Evidence citations are traceable back to source documents

### Meeting Integration Tests (Planned, Milestone 7 — Zoom integration)

Tests that verify meeting connector behavior (Zoom join/leave, audio stream, message delivery).

- Use Zoom's sandbox/developer environment
- Isolated from production
- Run manually before each release involving meeting connector changes
- Zoom feasibility spike (Milestone 6) must validate the test approach before these are written

---

## Current Tests (Milestone 0)

### Backend

```
services/api/tests/
├── conftest.py       — fixtures: TestClient with mocked database and Redis
├── test_health.py    — liveness (exact body, independent of deps), readiness (healthy,
│                        db down, redis down, both down, no sensitive data in response),
│                        X-Request-ID (generated UUID, accept valid incoming, reject malformed,
│                        reject oversized, independent across requests)
└── test_config.py    — Settings validation: defaults, env overrides, CWD independence,
                         timeout field existence, default DB URL password correctness,
                         production does not load .env, invalid env raises ValidationError
```

Run:
```bash
cd services/api
uv run pytest
```

### Frontend

```
apps/web/src/app/__tests__/
└── page.test.tsx     — Home component: heading and foundation label
```

Run:
```bash
cd apps/web
pnpm test
```

---

## Running Tests

### All tests
```bash
make test
```

### Backend only
```bash
cd services/api && uv run pytest
```

### Backend with coverage
```bash
cd services/api && uv run pytest --cov=app --cov-report=term-missing
```

### Backend verbose
```bash
cd services/api && uv run pytest -v
```

### Frontend only
```bash
cd apps/web && pnpm test
```

### Frontend watch mode
```bash
cd apps/web && pnpm test --watch
```

### Frontend coverage
```bash
cd apps/web && pnpm test --coverage
```

---

## CI Behavior

On every push to `milestone/*`, `fix/*`, and every PR to `main`:

| Job | What it does |
|---|---|
| `secret-scan` | Gitleaks against full git history — detects committed secrets |
| `infra-validate` | `docker compose config --quiet` — validates compose syntax |
| `frontend` | pnpm install, format check, lint, typecheck, test, build |
| `backend` | uv sync, ruff format check, ruff lint, pyright, pytest, import check |
| `migrations` | alembic upgrade → downgrade → re-upgrade (full cycle) |
| `audit` | `pip-audit` (Python CVEs) + `pnpm audit --audit-level high` (npm CVEs) |
| `runtime` | Start infrastructure via Docker Compose, run migration cycle, start Uvicorn, verify liveness/readiness/request-ID, then degradation + recovery tests for PostgreSQL, Redis, and both simultaneously |

All jobs must pass before a PR can be merged to `main`.

---

## Coverage Expectations

We do not enforce a hard coverage percentage. Instead:

- All new features must have tests
- All bug fixes must have a regression test
- Health check endpoints: 100% covered
- Config validation: 100% covered
- Auth endpoints (planned): 100% covered
- Business logic: > 80% line coverage expected

---

## Test Conventions

### Backend (Python)

- Test files named `test_*.py`
- Test functions named `test_<what>_<condition>`
- Fixtures in `conftest.py`
- Use `unittest.mock.patch` for external dependencies
- Mark slow tests with `@pytest.mark.slow`
- Mark integration tests with `@pytest.mark.integration`

### Frontend (TypeScript)

- Test files in `__tests__/` directories co-located with source
- Test files named `*.test.tsx` or `*.test.ts`
- Use `describe` blocks for grouping
- `it` or `test` for individual cases (prefer `it` for readability)
- Use `@testing-library/react` — avoid snapshot tests unless necessary

---

## Definition of Done

A feature is "done" when:
1. All specified behavior is implemented
2. Unit tests cover the new code
3. Integration tests cover the new API endpoints
4. `make check` passes (lint + typecheck + test + build)
5. PR has been reviewed
6. KNOWN_LIMITATIONS.md is updated if any limitations exist
