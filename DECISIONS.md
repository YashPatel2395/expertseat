# ExpertSeat — Architecture Decision Records

Decisions are numbered chronologically. Once recorded, decisions are not deleted — only superseded.

---

## ADR-001: Monorepo structure

**Date**: 2026-07-12
**Status**: Accepted

**Context**: We have a frontend (Next.js) and a backend (FastAPI) that need to be developed together. Separate repositories increase coordination overhead.

**Decision**: Single private GitHub repository with `apps/` for frontend services and `services/` for backend services.

**Reason**: Atomic commits spanning frontend and backend changes, unified CI, shared tooling configuration, easier onboarding.

**Alternatives considered**:
- Separate repos per service: rejected for increased coordination cost at this team size.
- Turborepo or Nx: not needed yet; simple scripts suffice for Milestone 0.

**Consequences**: All developers work in one repo. Build times may increase as the codebase grows. Turborepo or Nx can be introduced later if needed.

---

## ADR-002: Next.js 14 with App Router

**Date**: 2026-07-12
**Status**: Accepted

**Context**: The frontend is a recruiter-facing web application. Server-side rendering and good TypeScript support are important.

**Decision**: Next.js 14 with App Router (RSC-first).

**Reason**: App Router is the stable, recommended path for new Next.js projects. RSC reduces client bundle size. Strong ecosystem, good TypeScript integration.

**Alternatives considered**:
- Remix: strong candidate, but Next.js has broader ecosystem and more deployment options.
- Vite + React SPA: no SSR, no RSC; rejected.
- SvelteKit: considered but TypeScript ecosystem for our team is better in React.

**Consequences**: RSC patterns require careful attention to client vs. server component boundaries. Some libraries are not yet compatible.

---

## ADR-003: FastAPI for backend API

**Date**: 2026-07-12
**Status**: Accepted

**Context**: The backend needs to serve a REST API and orchestrate AI calls. Python is preferred for its AI/ML ecosystem.

**Decision**: FastAPI with Python 3.12.

**Reason**: FastAPI provides automatic OpenAPI generation, native async, Pydantic v2 integration, and excellent performance for an async workload. Python 3.12 for performance and type annotation improvements.

**Alternatives considered**:
- Django REST Framework: heavier, slower iteration; rejected.
- Node.js (Express/Hono): would unify language, but Python AI ecosystem is superior.
- Go: excellent performance, but harder to iterate with AI libraries.

**Consequences**: We have two languages in the monorepo. Python async patterns require care. AI library ecosystem availability is a strong advantage.

---

## ADR-004: PostgreSQL as primary database

**Date**: 2026-07-12
**Status**: Accepted

**Context**: The application needs relational data (orgs, users, blueprints, interviews, reports) with strong consistency guarantees.

**Decision**: PostgreSQL 16.

**Reason**: Battle-tested, ACID compliant, excellent JSON support (for flexible blueprint schemas), row-level security for org isolation, strong SQLAlchemy support.

**Alternatives considered**:
- MySQL: no row-level security; weaker JSON support.
- MongoDB: document model doesn't fit relational interview data well.
- SQLite: not suitable for production multi-user workloads.

**Consequences**: Managed RDS or equivalent required in production. Schema migrations must be managed carefully.

---

## ADR-005: SQLAlchemy 2.0 as ORM

**Date**: 2026-07-12
**Status**: Accepted

**Context**: We need an ORM to abstract database queries and enable safe parameterized queries.

**Decision**: SQLAlchemy 2.0 with declarative models and Alembic for migrations.

**Reason**: SQLAlchemy 2.0 has a cleaner async-first API. Alembic is the standard migration tool for SQLAlchemy. Strong ecosystem and documentation.

**Alternatives considered**:
- Tortoise ORM: async-first but smaller ecosystem.
- raw SQL: flexible but unsafe without discipline; rejected.
- Prisma (Python client): immature.

**Consequences**: SQLAlchemy 2.0 async patterns require explicit session management. Alembic migration files must be reviewed carefully.

---

## ADR-006: Redis for caching and sessions

**Date**: 2026-07-12
**Status**: Accepted

**Context**: We need a fast key-value store for JWT refresh token storage, session data, and possibly agent state.

**Decision**: Redis 7.

**Reason**: Redis is the industry standard for this use case. Supports TTL on keys (useful for token expiry). Fast, well-understood operationally.

**Alternatives considered**:
- In-memory store: not viable across multiple API instances.
- DynamoDB / equivalent: adds cloud vendor dependency; more complex.

**Consequences**: Redis must be highly available in production. Redis Sentinel or Redis Cluster needed for production (Milestone 9).

---

## ADR-007: pnpm as frontend package manager

**Date**: 2026-07-12
**Status**: Accepted

**Context**: npm and yarn have known performance and reliability issues with large dependency trees.

**Decision**: pnpm.

**Reason**: Faster installs, content-addressable store, strict dependency resolution, native workspace support.

**Alternatives considered**:
- npm: slower, less strict.
- yarn 3+: PnP mode causes compatibility issues with many packages.

**Consequences**: All developers must have pnpm installed. CI must use pnpm.

---

## ADR-008: uv as Python package manager

**Date**: 2026-07-12
**Status**: Accepted

**Context**: pip and poetry are slow. We want fast, reproducible Python dependency management.

**Decision**: uv.

**Reason**: Dramatically faster than pip. Lock file support. Built-in virtual environment management. Compatible with pyproject.toml.

**Alternatives considered**:
- poetry: slower; resolver has edge cases.
- conda: heavyweight; not needed.
- pip + requirements.txt: no lock file semantics.

**Consequences**: All developers must install uv. CI uses uv. The lock file must be committed.

---

## ADR-009: Ruff for Python linting and formatting

**Date**: 2026-07-12
**Status**: Accepted

**Context**: We need a Python linter and formatter that is fast and covers multiple rules.

**Decision**: Ruff (lint + format).

**Reason**: Ruff is 10–100x faster than alternatives. Replaces flake8, isort, and black in a single tool. Strong defaults for new projects.

**Alternatives considered**:
- Black + flake8 + isort: slower, three tools to configure.
- pylint: verbose, slow.

**Consequences**: Ruff configuration in pyproject.toml. All code must pass ruff before merge.

---

## ADR-010: Pyright for Python type checking

**Date**: 2026-07-12
**Status**: Accepted

**Context**: FastAPI and Pydantic benefit strongly from static type checking. We want type safety without the slowness of mypy.

**Decision**: Pyright in basic mode.

**Reason**: Faster than mypy. Works well with Pydantic v2. VS Code integration via Pylance.

**Alternatives considered**:
- mypy: slower, less Pydantic v2 support.
- No type checker: unacceptable for a production codebase.

**Consequences**: pyright must pass in CI. `basic` mode is less strict than `strict`; we may increase strictness as the codebase matures.

---

## ADR-011: Vitest for frontend testing

**Date**: 2026-07-12
**Status**: Accepted

**Context**: We need a fast test runner for React components.

**Decision**: Vitest with @testing-library/react.

**Reason**: Vitest is native ESM, very fast, Vite-compatible, similar API to Jest. @testing-library/react is the standard for component testing.

**Alternatives considered**:
- Jest: slower with ESM; requires more configuration with Next.js.
- Playwright for component tests: heavier than needed for unit tests.

**Consequences**: Vitest config must be compatible with Next.js module resolution. Some Next.js internals (Server Components) are harder to test in Vitest.

---

## ADR-012: AI provider abstraction layer

**Date**: 2026-07-12
**Status**: Planned (not yet implemented)

**Context**: We will use LLMs for Role Agent behavior. LLM provider landscape is evolving rapidly. We should not be locked into one provider.

**Decision**: Implement an AI provider abstraction Protocol (planned for Milestone 3). Initial implementation: OpenAI GPT-4o.

**Reason**: Protocol-based abstraction allows switching providers per Blueprint or per org. Reduces migration cost if a provider degrades or pricing changes.

**Alternatives considered**:
- LiteLLM: convenient but adds a dependency and may lag behind provider API changes.
- Direct OpenAI SDK calls: creates lock-in.
- LangChain: too heavyweight and opinionated for our structured agent use case.

**Consequences**: Abstraction layer adds development cost up front. Must be careful not to over-abstract before we understand the full requirements.

---

## ADR-013: Meeting connector abstraction

**Date**: 2026-07-12
**Status**: Planned (not yet implemented)

**Context**: We will integrate with video conferencing platforms. These APIs are complex and change frequently.

**Decision**: Implement a MeetingConnector Protocol abstraction (planned for Milestone 5). Initial implementation: Zoom.

**Reason**: Protocol abstraction allows adding Google Meet, Teams, etc. without rewriting agent logic. Zoom chosen first for its bot SDK maturity.

**Alternatives considered**:
- Recall.ai or Symbl.ai: third-party aggregators. Convenient but adds a vendor and raises data privacy questions.
- Direct Zoom SDK only: creates lock-in.

**Consequences**: Additional complexity in Milestone 5. Recall.ai should be re-evaluated at that milestone.

---

## ADR-014: Disclosed AI participation only

**Date**: 2026-07-12
**Status**: Accepted (product principle, not technical)

**Context**: AI agents participating in interviews without disclosure would be deceptive and potentially illegal in some jurisdictions.

**Decision**: ExpertSeat will never allow an AI agent to participate in an interview without explicit candidate disclosure and consent.

**Reason**: Ethical requirement. Increasingly a legal requirement in various jurisdictions (EU AI Act, US state laws). Also a reputational requirement.

**Alternatives considered**: None — this is non-negotiable.

**Consequences**: Consent flow is a hard requirement before every interview. This adds friction but is correct.

---

## ADR-015: Org isolation via application layer + RLS

**Date**: 2026-07-12
**Status**: Planned

**Context**: All data must be strictly isolated between organizations. A bug allowing org A to see org B's data would be a critical security failure.

**Decision**: Enforce org isolation at both the application layer (every query includes org_id filter) and the database layer (PostgreSQL RLS policies).

**Reason**: Defense in depth. Application-layer filtering catches most issues. RLS provides a safety net if a query is written without an org filter.

**Alternatives considered**:
- Application layer only: single point of failure.
- Separate database per org: operational complexity doesn't justify it at this scale.

**Consequences**: All models must have an org_id column. All repository functions must accept and apply an org filter. RLS policies must be tested.

---

## ADR-016: Structured logging with structlog

**Date**: 2026-07-12
**Status**: Accepted

**Context**: Application logs must be machine-parseable for production observability.

**Decision**: structlog for Python backend logging, outputting JSON in production.

**Reason**: structlog integrates with Python's stdlib logging, supports structured key-value context, and produces JSON output compatible with log aggregation systems (Datadog, CloudWatch, etc.).

**Alternatives considered**:
- stdlib logging only: unstructured output, hard to query in production.
- loguru: good, but structlog has better structured output story.

**Consequences**: All log calls must use structlog. Log context (org_id, user_id, request_id) should be bound at request start.

---

## ADR-017: Alembic for database migrations

**Date**: 2026-07-12
**Status**: Accepted

**Context**: We need a migration tool that integrates with SQLAlchemy and supports production-safe schema changes.

**Decision**: Alembic.

**Reason**: Standard SQLAlchemy migration tool. Supports autogenerate from model diffs. Supports both upgrade and downgrade. Well-documented.

**Alternatives considered**:
- Django migrations: we're not using Django.
- Flyway / Liquibase: Java-based, adds JVM dependency.
- Raw SQL migrations: no autogenerate, harder to maintain.

**Consequences**: All schema changes must go through Alembic migrations. Migrations must be reviewed before merge. Production deployments must run `alembic upgrade head` before starting new app version.

---

## ADR-018: No AI voice synthesis

**Date**: 2026-07-12
**Status**: Accepted (product principle)

**Context**: AI voice synthesis could make the agent seem more human, potentially increasing deception risk even when disclosed.

**Decision**: ExpertSeat will not implement AI voice synthesis for Role Agents.

**Reason**: Synthetic voice increases the risk of candidate confusion about whether they are speaking with a human, even when disclosure is present. The product benefit does not outweigh this risk.

**Alternatives considered**:
- Text-to-speech for accessibility: may be reconsidered for accessibility use cases only, with clear UI labeling.

**Consequences**: Agents communicate via text in all meeting integrations.

---

## ADR-019: GitHub Actions for CI

**Date**: 2026-07-12
**Status**: Accepted

**Context**: We need a CI system that integrates with GitHub.

**Decision**: GitHub Actions.

**Reason**: Native GitHub integration. No additional service to operate. Free tier sufficient for a private repo at this stage.

**Alternatives considered**:
- CircleCI: more configuration, external service.
- Jenkins: operational overhead not justified.
- GitLab CI: would require platform migration.

**Consequences**: CI runs on GitHub-hosted runners. We are subject to GitHub Actions pricing and uptime. Secrets managed via GitHub repository secrets.
