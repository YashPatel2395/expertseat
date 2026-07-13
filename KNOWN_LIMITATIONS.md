# ExpertSeat — Known Limitations

**As of**: Milestone 0 (Foundation — audit remediation 2026-07-13)
**Date**: 2026-07-13

This document is an honest statement of what ExpertSeat does and does not do.

---

## What Is Implemented

As of Milestone 0, ExpertSeat is a repository foundation. The following are implemented:

- **Next.js 16 frontend**: A single-page application that displays the ExpertSeat name and a description. No interactive functionality.
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
- Meeting connector integrations (Zoom is planned; Google Meet is not in scope)
- Audit logging
- Data retention controls
- Candidate portal
- ATS integrations
- Production deployment

---

## Process Limitations (Milestone 0)

- **Original PR #7 is non-reviewable**: All foundation commits went directly to `main`; PR #7 shows only a single file. The audit remediation branch `fix/m0-audit-remediation` (PR #12) is the correct review target.
- **Repository is public**: Changed from private (original spec) to public on 2026-07-13 per owner decision.
- **Dependency Review (GitHub Advanced Security)**: GHAS is not available at the current plan tier. The `dependency-review.yml` workflow was removed. Proactive dependency scanning is provided by `pip-audit` (Python) and `pnpm audit --audit-level high` (npm), both run in CI. Dependabot provides reactive PR-based alerts.
- **No AI panelist is implemented**: The AI Role Agent does not exist yet. Milestone 4 will introduce a text-based browser simulator as the first functional interview experience. Milestones 6–8 will validate and implement live Zoom participation with audio input and AI-generated speech. There is no audio/TTS integration at any milestone prior to that validation spike.

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
- **ExpertSeat cannot evaluate all types of roles.** Roles requiring physical demonstration, creative portfolio review, or highly context-dependent judgment may not be well-served by AI panels.
- **ExpertSeat's data retention policy is not yet defined.** Retention periods for interview recordings, transcripts, and reports require legal and privacy review before defaults are established. No retention defaults are specified in Milestone 0.
