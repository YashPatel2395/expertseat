# ExpertSeat

> Add the missing expert to any interview panel.

ExpertSeat is a recruiter-controlled AI interview panelist platform. AI Role Agents participate as **disclosed panelists** in live technical interviews, ask evidence-backed questions, and produce structured reports that human reviewers assess.

---

## What ExpertSeat Is

- A platform where recruiters can add AI panelists with specific domain expertise to interview panels
- A system where AI agents ask questions grounded in verified evidence (job descriptions, domain knowledge, candidate submissions)
- A tool that produces structured, human-reviewable interview reports
- Fully disclosed to candidates — no deception

## What ExpertSeat Is Not

- ExpertSeat is **not** an autonomous hiring decision system
- ExpertSeat does **not** replace human judgment
- ExpertSeat does **not** claim objectivity or bias-freedom
- ExpertSeat is **not** currently functional — only the foundation is implemented

---

## Current Status

**Milestone 0 — Production Foundation** (in progress)

The repository contains infrastructure, tooling, CI, and documentation. No product features are yet implemented.

See [ROADMAP.md](./ROADMAP.md) for the full milestone plan.

---

## Repository Structure

```
expertseat/
├── apps/web/           Next.js 16 frontend (App Router, TypeScript, React 19)
├── services/api/       FastAPI backend (Python 3.12)
├── infrastructure/     Docker Compose for local services
├── scripts/            Developer utility scripts
├── .github/            GitHub Actions CI and Dependabot config
└── docs (root)         Product spec, architecture, roadmap, decisions
```

---

## Prerequisites

- **Node.js 24** — `nvm install 24` or use `.nvmrc`
- **pnpm 11.12.0** — via Corepack (bundled with Node.js): `corepack enable pnpm && corepack prepare pnpm@11.12.0 --activate`
- **Python 3.12** — `pyenv install 3.12` or system package manager
- **uv 0.11.7** — `pip install uv==0.11.7` or `brew install uv` then pin the version
- **Docker and Docker Compose** — required for `make check` and local infrastructure
- **Gitleaks 8.30.1** — `brew install gitleaks` (reviewed version: 8.30.1; newer versions accepted)

Verify installed versions:
```bash
node --version          # v24.x.x
pnpm --version          # 11.12.0
python3 --version       # Python 3.12.x
uv --version            # uv 0.11.7
gitleaks version        # 8.30.1
docker --version        # 27+ or Docker Desktop
```

---

## Quick Start

```bash
# 1. Clone the repo
git clone git@github.com:YashPatel2395/expertseat.git
cd expertseat

# 2. Copy and configure environment
cp .env.example .env
# Edit .env with your values

# 3. Install all dependencies
make setup

# 4. Start local infrastructure
make dev-infra

# 5. Run database migrations
make migrate

# 6. Start development servers (in separate terminals)
make dev
```

---

## Commands

| Command | Description |
|---|---|
| `make setup` | Install all frontend and backend dependencies (locked — uses `--frozen-lockfile` and `--locked`) |
| `make dev-infra` | Start PostgreSQL and Redis via Docker Compose |
| `make dev-infra-wait` | Start infrastructure and wait until health checks pass |
| `make dev` | Print instructions for starting all dev servers |
| `make format` | Auto-format all code (ruff + prettier) |
| `make format-check` | Check formatting without modifying files |
| `make lint` | Lint Python (ruff) and TypeScript (eslint) |
| `make typecheck` | Type-check Python (pyright) and TypeScript (tsc) |
| `make test` | Run all tests (pytest + vitest) |
| `make migrate` | Apply Alembic migrations to head |
| `make migrate-down` | Roll back all Alembic migrations |
| `make migrate-full` | Upgrade → downgrade → upgrade (full cycle verification) |
| `make build` | Production build of the Next.js frontend |
| `make infra-validate` | Validate Docker Compose configuration (no services started) |
| `make secret-scan` | Run Gitleaks secret scan against git history (requires gitleaks) |
| `make check` | Complete 54-step quality gate — requires Docker running (versions, static analysis, infrastructure, runtime, security) |
| `make stop` | Stop Docker Compose services |
| `make clean` | Stop services and remove build caches |

---

## Services

| Service | Default URL | Notes |
|---|---|---|
| Frontend | http://localhost:3000 | Next.js dev server |
| API | http://localhost:8000 | FastAPI with auto-docs at /api/docs |
| PostgreSQL | localhost:5432 | Database: expertseat |
| Redis | localhost:6379 | Cache / session store |

---

## Documentation

- [PRODUCT_SPEC.md](./PRODUCT_SPEC.md) — Full product specification
- [ARCHITECTURE.md](./ARCHITECTURE.md) — System architecture (current + planned)
- [ROADMAP.md](./ROADMAP.md) — Milestone plan
- [DECISIONS.md](./DECISIONS.md) — Architecture decision records
- [SECURITY.md](./SECURITY.md) — Security principles and policies
- [TESTING.md](./TESTING.md) — Testing strategy and conventions
- [RISK_REGISTER.md](./RISK_REGISTER.md) — Risk tracking
- [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md) — Honest limitations statement
- [CONTRIBUTING.md](./CONTRIBUTING.md) — Contribution guidelines

---

## License

Copyright 2026 Yash Patel. All rights reserved.

This repository is public for transparency, portfolio, and review purposes. No license is granted to copy, use, modify, or distribute this software or its documentation without explicit written permission from the author.
