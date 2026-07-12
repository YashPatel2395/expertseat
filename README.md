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
├── apps/web/           Next.js 14 frontend (App Router, TypeScript)
├── services/api/       FastAPI backend (Python 3.12)
├── infrastructure/     Docker Compose for local services
├── scripts/            Developer utility scripts
├── .github/            GitHub Actions CI and Dependabot config
└── docs (root)         Product spec, architecture, roadmap, decisions
```

---

## Prerequisites

- Node.js 20+ and pnpm 8+
- Python 3.12+ and uv
- Docker and Docker Compose

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
| `make setup` | Install all frontend and backend dependencies |
| `make dev-infra` | Start PostgreSQL and Redis via Docker Compose |
| `make dev` | Print instructions for starting all dev servers |
| `make migrate` | Run Alembic database migrations |
| `make format` | Format Python (ruff) and TypeScript (prettier) code |
| `make lint` | Lint Python (ruff) and TypeScript (eslint) code |
| `make typecheck` | Type-check Python (pyright) and TypeScript (tsc) |
| `make test` | Run all tests (pytest + vitest) |
| `make build` | Build the Next.js frontend |
| `make check` | Full quality gate: lint + typecheck + test + build |
| `make clean` | Stop Docker services and remove build caches |

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

Private — all rights reserved. See repository settings.
