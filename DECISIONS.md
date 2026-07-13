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

## ADR-002: Next.js with App Router

**Date**: 2026-07-12
**Revised**: 2026-07-13 (Milestone 0 audit — upgraded from 14 to 16)
**Status**: Accepted

**Context**: The frontend is a recruiter-facing web application. Server-side rendering and good TypeScript support are important.

**Decision**: Next.js 16 (Active LTS) with App Router (RSC-first), React 19, Node.js 24 LTS.

**Reason**: App Router is the stable, recommended path for new Next.js projects. RSC reduces client bundle size. Strong ecosystem, good TypeScript integration. Next.js 14 was initially selected but is no longer actively supported; Next.js 16 is the current Active LTS release. Tailwind CSS v4 is now the default with Next.js 16 via Turbopack. ESLint 9 flat config required by eslint-config-next 16.x.

**Alternatives considered**:
- Remix: strong candidate, but Next.js has broader ecosystem and more deployment options.
- Vite + React SPA: no SSR, no RSC; rejected.
- SvelteKit: considered but TypeScript ecosystem for our team is better in React.

**Consequences**: RSC patterns require careful attention to client vs. server component boundaries. Some libraries are not yet compatible. ESLint 9 flat config requires maintaining `eslint.config.js` instead of `.eslintrc.json`.

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

## ADR-018: No AI voice synthesis ⚠️ SUPERSEDED by ADR-020

**Date**: 2026-07-12
**Superseded**: 2026-07-13 by ADR-020
**Status**: Superseded

**Context**: At initial foundation, AI voice synthesis was considered potentially deceptive even when disclosed.

**Original decision**: ExpertSeat will not implement AI voice synthesis for Role Agents.

**Why superseded**: The Master Project Specification clarifies that Zoom participation requires two-way audio: the Role Agent must receive meeting audio (for transcription) and return synthesized speech (TTS) to the meeting. A text-chat-only agent is not the target product. Disclosed TTS with a clearly named AI participant is the required approach. ADR-020 records the corrected decision.

**See**: ADR-020 (Disclosed text-to-speech for Zoom participation)

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

---

## ADR-020: Disclosed text-to-speech for Zoom participation

**Date**: 2026-07-13
**Status**: Accepted
**Supersedes**: ADR-018

**Context**: ExpertSeat's target product requires AI Role Agents to participate verbally in live Zoom interviews — not as a text-only chat participant. The Zoom integration must capture audio from the meeting (for transcription) and return AI-generated speech to the meeting. Without TTS, the product does not achieve its stated goal of adding an AI expert as a verbal interview panelist.

**Decision**: ExpertSeat will implement disclosed text-to-speech for Role Agent verbal participation in Zoom meetings. The following constraints are non-negotiable:

1. The participant is clearly named as AI (e.g., "ExpertSeat — AI Panelist") in the meeting interface.
2. No generated humanlike video avatar. A static profile image is acceptable.
3. The agent joins muted by default. Recruiters control activation.
4. Recruiters control every agent speech event (activate, mute, deactivate, takeover).
5. TTS voice must not be designed to impersonate a specific human.
6. No voice-confidence, accent, emotion, or personality scoring of candidates is permitted.
7. No inference about candidate characteristics from voice other than the spoken content transcription.

**Reason**: Without TTS, Zoom participation cannot deliver on the product's core proposition. Disclosed TTS with explicit recruiter control and a named AI participant preserves the product's ethical requirements while enabling verbal participation. The risks of deception are addressed by the disclosure and control requirements, not by eliminating audio.

**Alternatives considered**:
- Text-only chat participation: does not meet the target product specification; the agent cannot ask questions verbally or participate naturally in a live panel.
- Human voice actor reading AI output: impractical at scale and raises its own disclosure concerns.
- No Zoom integration: would require a different meeting product; deferred to feasibility spike evaluation.

**Consequences**: TTS provider selection becomes an architecture decision (Milestone 6). Provider must be evaluated against latency, quality, and data-usage terms. Candidate consent disclosure must specify that AI speech is synthesized. TTS latency and interruption behavior must be tested in the feasibility spike (Milestone 6) before committing to the full Zoom integration (Milestone 7).

---

## ADR-021: Zoom first, Webex later, Google Meet out of scope

**Date**: 2026-07-13
**Status**: Accepted

**Context**: Multiple meeting platforms are in use by enterprise customers. The roadmap must state clearly which platforms are targeted and in what order.

**Decision**:
- Zoom is the first meeting platform to integrate (Milestone 7).
- Webex may be added after Zoom is stable in production. It is not committed.
- Google Meet is explicitly out of scope for the initial MVP and is not in the committed roadmap.

**Reason**: Zoom has more mature bot SDK options and a larger enterprise install base among the initial target customers. Committing to multiple platforms simultaneously increases complexity and risk. Google Meet's programmatic bot access model differs significantly and requires a separate feasibility evaluation.

**Alternatives considered**:
- Google Meet first: meet's bot APIs require different architecture; not yet validated.
- All platforms simultaneously: too much scope; deferred.
- Teams: may be evaluated post-pilot; not committed.

**Consequences**: Milestone 6 (Zoom feasibility spike) must succeed before Milestone 7 begins. If the Zoom integration proves infeasible, the decision on which platform to try next must be made at that time and recorded as an ADR update.

---

## ADR-022: Browser interview simulator before Zoom integration

**Date**: 2026-07-13
**Status**: Accepted

**Context**: The Zoom integration is technically risky (two-way audio, waiting-room behavior, platform review). The interview engine (Role Agent questions, evidence tracking, recruiter controls, report generation) must be proven before connecting it to a live meeting platform.

**Decision**: The browser-based interview simulator (Milestone 4) must be completed and accepted before the Zoom feasibility spike (Milestone 6). No Zoom integration work begins until the simulator milestone has passed its exit criteria.

**Reason**: If the interview engine has fundamental problems, those must be discovered and fixed in a low-risk controlled environment (the simulator) rather than during a live Zoom session. This separation also ensures that the MeetingConnector abstraction is clean — the interview engine is proved first, then connected to Zoom without changes to the core interview logic.

**Alternatives considered**:
- Develop Zoom integration in parallel with the simulator: risks propagating engine bugs into a harder-to-test context.
- Skip the simulator and go straight to Zoom: dramatically increases integration risk.

**Consequences**: The overall timeline to Zoom integration is longer than if both were developed in parallel. This is an intentional trade-off for reliability.

---

## ADR-023: Dependency Review workflow replaced by Gitleaks for secret scanning

**Date**: 2026-07-13
**Revised**: 2026-07-13 (Round 2 audit — scope corrected)
**Status**: Accepted

**Context**: The initial CI included `actions/dependency-review-action`, which requires GitHub Advanced Security (GHAS). GHAS is not available at the current repository plan tier. The workflow failed on every PR.

**Decision**: Remove the `dependency-review.yml` workflow. Add Gitleaks (`gitleaks/gitleaks-action`) for **secret scanning** — detecting committed credentials, API keys, and tokens in git history. Add `pip-audit` and `pnpm audit` in a separate `audit` CI job for **dependency vulnerability scanning** (CVEs in pinned packages). Dependabot continues to provide automated dependency update PRs.

**Important scope distinction**: Gitleaks scans for **committed secrets** (hardcoded credentials). It does not scan for **CVEs in dependencies** — those are separate concerns addressed by `pip-audit`, `pnpm audit`, and Dependabot.

**Reason**: A permanently failing workflow trains contributors to ignore CI failures. Gitleaks provides secret detection without GHAS. `pip-audit` and `pnpm audit` provide blocking CVE scanning without GHAS. Dependabot provides ongoing vulnerability alerts.

**Alternatives considered**:
- Enable GHAS: not available at current plan.
- Keep the failing workflow and document it: creates a habituation problem with red CI.
- Trivy or Grype for SCA: valid alternatives; `pip-audit` + `pnpm audit` are simpler and sufficient at this stage.

**Consequences**: Secret scanning and vulnerability scanning run as separate CI jobs. If the plan is upgraded to include GHAS, the dependency-review workflow can be reinstated alongside these.

---

## ADR-024: Structured logging configuration with structlog

**Date**: 2026-07-13
**Status**: Accepted

**Context**: `structlog` was declared as a dependency but `structlog.configure()` was never called. Without explicit configuration, structlog uses default behavior: no timestamps, no log levels in standard format, and output varies by context. This is not acceptable for production observability.

**Decision**: Call `structlog.configure()` at application startup before any logger is created. Use different processor chains for production (JSON output) and non-production (console output). Bind a request ID to the structlog context at request entry via middleware.

**Configuration**:
- **Production**: `merge_contextvars`, `add_log_level`, `TimeStamper(iso)`, `dict_tracebacks`, `JSONRenderer()` — machine-parseable JSON for log aggregation systems.
- **Development/test**: `merge_contextvars`, `add_log_level`, `TimeStamper(iso)`, `ConsoleRenderer()` — human-readable output.
- **Request ID middleware**: Generates a UUID per request, binds it to structlog contextvars, returns it in `X-Request-ID` response header.
- **Exception handler**: Logs `exc_type=type(exc).__name__` only — never `str(exc)` which may contain sensitive data.

**Reason**: JSON structured logs are required for production log aggregation (Datadog, CloudWatch, etc.). Request IDs are essential for correlating log lines for a single request. The exception handler must not leak internal error details to logs.

**Alternatives considered**:
- stdlib logging only: unstructured, hard to query in production.
- loguru: good, but structlog is already the declared dependency.
- Sentry for exception capture: valid for production error tracking; can be added alongside structlog.

**Consequences**: `structlog.configure()` must be called before any `get_logger()`. Application code must use `structlog.get_logger()` — not `logging.getLogger()`. Tests that import `app.main` will use the configured structlog pipeline.

---

## ADR-025: GitHub Actions upgraded to Node.js 24 runtime

**Date**: 2026-07-13
**Status**: Accepted

**Context**: All GitHub Actions used in CI (checkout, setup-node, setup-python, cache, setup-uv, gitleaks-action, pnpm/action-setup) were pinned to versions that use Node.js 20 as their internal runtime. GitHub deprecated Node.js 20 for Actions on June 2, 2026 (requiring opt-in to continue) and will remove it entirely on September 16, 2026.

**Decision**: Update all action SHA pins to versions that use Node.js 24 internally:

| Action | Old version | New version |
|---|---|---|
| actions/checkout | v4.2.2 | v7.0.0 |
| actions/setup-node | v4.4.0 | v6.4.0 |
| pnpm/action-setup | v4.1.0 | v6.0.9 |
| actions/cache | v4.2.3 | v6.1.0 |
| actions/setup-python | v5.6.0 | v6.3.0 |
| astral-sh/setup-uv | v6.3.1 | v8.3.2 |
| gitleaks/gitleaks-action | v2.3.9 | v3.0.0 |

All updated actions use Node.js 24 for their internal runtime. All inputs used in this repository are unchanged between old and new versions.

**Reason**: Node.js 20 will be removed from GitHub-hosted runners on September 16, 2026. Upgrading now eliminates deprecation warnings and ensures CI continues to work after that date.

**Alternatives considered**:
- Set `ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION=true`: only works until September 16, 2026; not a fix.
- Stay on current versions: CI will break in September 2026.

**Consequences**: All action SHAs must be updated as a coordinated change. SHA pins remain immutable — each new version gets a new SHA. New self-hosted runners must be version >= 2.327.1 to support Node.js 24 action runtime.
