# ExpertSeat — Known Limitations

**As of**: Milestone 0 (Foundation)
**Date**: 2026-07-12

This document is an honest statement of what ExpertSeat does and does not do.

---

## What Is Implemented

As of Milestone 0, ExpertSeat is a repository foundation. The following are implemented:

- **Next.js 14 frontend**: A single-page application that displays the ExpertSeat name and a description. No interactive functionality.
- **FastAPI backend**: Two health check endpoints (`/api/v1/health/live` and `/api/v1/health/ready`). No business logic.
- **PostgreSQL database**: Running via Docker Compose. No schema exists yet.
- **Redis**: Running via Docker Compose. Not used by the application yet.
- **Alembic**: Migration tooling configured. One placeholder migration exists (no-op).
- **CI**: GitHub Actions workflows for lint, typecheck, test, and build.
- **Documentation**: Product spec, architecture, roadmap, decisions, security, testing, risk register, contributing guide.

---

## What Is Not Implemented

**Everything described in the product spec is not yet implemented.** This includes:

- User accounts and authentication
- Organization management
- Blueprint creation or management
- Candidate records
- Interview scheduling
- Consent delivery or recording
- Role Agent / AI panelist functionality
- Any AI model integration
- Interview sessions (text or video)
- Report generation
- Human review workflow
- Meeting connector integrations (Zoom, Google Meet)
- Audit logging
- Data retention controls
- Candidate portal
- ATS integrations
- Production deployment

---

## Why This Document Exists

It is important to be explicit about the gap between what a product spec describes and what is actually working. The product spec and architecture documents describe an ambitious planned system. None of that system exists yet.

This document will be updated at each milestone to reflect what has changed.

---

## Limitations That Will Persist (By Design)

Even when ExpertSeat is fully implemented:

- **ExpertSeat will not make hiring decisions.** It produces reports that humans review.
- **ExpertSeat does not guarantee fairness.** AI systems reflect the data they were trained on and the rubrics they are given. We cannot claim to eliminate bias.
- **ExpertSeat does not operate on undisclosed AI participation.** Consent is required. If a candidate refuses, the interview cannot use ExpertSeat.
- **ExpertSeat's AI agents are bounded by provided evidence.** They do not have general internet access during interviews.
- **ExpertSeat cannot evaluate all types of roles.** Roles requiring physical demonstration, creative portfolio review, or highly context-dependent judgment may not be well-served by text-based AI panels.
