# ExpertSeat — Roadmap

**Last Updated**: 2026-07-13
**Revised**: Milestone 0 audit remediation — milestone sequence corrected per Master Project Specification

Milestones are sequential unless a dependency is explicitly noted. Each has entry criteria (what must be true before it starts) and exit criteria (what must be true before the next milestone begins).

---

## Milestone 0 — Repository Audit and Foundation

**Goal**: Establish a production-grade repository with CI, infrastructure, and documentation. No product features. Includes remediation of any audit findings before the milestone is closed.

**Status**: In Progress (remediation branch: `fix/m0-audit-remediation`)

**Deliverables**:
- [x] GitHub repository (public per owner decision; originally intended private)
- [x] Next.js 16 frontend (branding and foundation notice only — no product features)
- [x] FastAPI backend with liveness and readiness health endpoints
- [x] PostgreSQL 16 + Redis 7 via Docker Compose with health checks
- [x] Alembic migration tooling configured with initial zero-op migration
- [x] GitHub Actions CI: format, lint, typecheck, test, build, migrations, secret scan
- [x] Gitleaks secret scanning against full git history
- [x] Dependabot for npm and pip
- [x] pnpm 11 workspace with root lockfile, pinned via `packageManager`
- [x] Node.js 24 LTS pinned via `.nvmrc` and `.node-version`
- [x] GitHub Actions pinned to immutable commit SHAs
- [x] Comprehensive documentation (README, PRODUCT_SPEC, ARCHITECTURE, DECISIONS, SECURITY, TESTING, RISK_REGISTER, KNOWN_LIMITATIONS, CONTRIBUTING)
- [x] All quality gates passing locally and in CI

**Entry criteria**: None (first milestone)

**Exit criteria**:
- CI passing on `fix/m0-audit-remediation` replacement PR
- All items above checked
- Documentation matches Master Project Specification
- No fake product features present
- No profession-specific hardcoding in universal logic
- No secrets committed
- Replacement draft PR open and linked; original PR #7 closed as superseded

---

## Milestone 1 — Authentication and Company Workspace

**Goal**: Implement organization accounts, user accounts, and authentication with strict organization isolation.

**Status**: Not Started

**Deliverables**:
- [ ] Organization entity (name, slug, settings)
- [ ] User entity (email, hashed password, role: recruiter/admin)
- [ ] JWT authentication (login, logout, token refresh)
- [ ] Role-based access control (recruiter, org-admin)
- [ ] Organization isolation enforced at every query boundary
- [ ] Audit log table for authentication events
- [ ] Frontend: login page, protected route shell
- [ ] Database migrations for organizations, users, audit_logs
- [ ] Organization isolation integration tests
- [ ] Auth API tests (login, logout, refresh, invalid credentials)

**Entry criteria**: Milestone 0 draft PR accepted and merged to main

**Exit criteria**:
- A recruiter can create an account, log in, and log out
- All queries are scoped to the authenticated organization
- Cross-organization access is rejected with 403
- Auth endpoints documented
- Org isolation tests pass

---

## Milestone 2 — Domain-Agnostic Blueprint Builder

**Goal**: Recruiters can create and version Interview Blueprints for any profession.

**Status**: Not Started

**Deliverables**:
- [ ] Blueprint entity: domain, role context, evaluation dimensions, question bank, rubrics, behavioral constraints
- [ ] Blueprint versioning (immutable published versions)
- [ ] Evidence attachment: job description, reference material
- [ ] Evidence processing pipeline (chunking, storage)
- [ ] Custom vs. Verified status tracking on blueprint records
- [ ] Frontend: Blueprint builder form, version history, evidence upload
- [ ] Database migrations for blueprints, blueprint_versions, evidence_documents
- [ ] Domain-agnostic schema validation (no profession-specific fields)
- [ ] Blueprint API tests

**Entry criteria**: Milestone 1 merged

**Exit criteria**:
- A recruiter can create a Blueprint, configure evaluation dimensions for any domain, and upload reference material
- Blueprint versions are immutable once published
- Custom Blueprints are clearly labeled as unverified
- No profession-specific assumptions in schema or logic

---

## Milestone 3 — Candidate and Interview Management

**Goal**: Manage candidates, schedule interviews, and record consent.

**Status**: Not Started

**Deliverables**:
- [ ] Candidate entity (name, contact, linked submissions)
- [ ] Interview entity (blueprint version, candidate, scheduled time, status)
- [ ] Consent workflow: template configuration, delivery, timestamped record
- [ ] Consent verification gate (interview cannot proceed without consent record)
- [ ] Interview lifecycle state machine (scheduled → consented → active → complete)
- [ ] Frontend: candidate list, interview scheduling, consent template, interview status
- [ ] Database migrations for candidates, interviews, consent_records

**Entry criteria**: Milestone 2 merged

**Exit criteria**:
- A recruiter can add a candidate, schedule an interview against a Blueprint, and record consent
- An interview without a consent record cannot be activated
- State transitions are enforced and logged

---

## Milestone 4 — Controlled Browser Interview Simulator

**Goal**: Full end-to-end interview flow in the browser — no Zoom integration — to prove the interview engine before connecting to a meeting platform.

**Status**: Not Started

**Deliverables**:
- [ ] Browser-based interview room (text interaction, no real-time audio)
- [ ] AI provider abstraction layer (initial provider: configurable, no hardcoded choice)
- [ ] Role Agent question generation from blueprint + evidence
- [ ] Adaptive follow-up logic within configured limits
- [ ] Evidence citation tracking: every agent output linked to a source
- [ ] Recruiter controls: activate, deactivate, manually override agent
- [ ] Post-interview: structured observation log (question, response, evidence, score candidate)
- [ ] "No evidence, no score" enforcement — insufficient evidence produces explicit flag
- [ ] Database migrations for interview_events, agent_observations
- [ ] Full simulator integration tests (consent → agent questions → observations)

**Entry criteria**: Milestone 3 merged, AI provider API key available in CI environment

**Exit criteria**:
- A complete simulated interview can run browser-to-database
- Evidence citations are present on every scored observation
- Recruiter can stop the agent at any point
- Observations without evidence are flagged, not scored
- All tests pass

---

## Milestone 5 — Evidence and Reporting Engine

**Goal**: Generate structured reports from interview observations and support human review.

**Status**: Not Started

**Deliverables**:
- [ ] Post-interview report generation (questions asked, candidate responses, scored observations, evidence citations)
- [ ] Report entity and storage
- [ ] Human review workflow: accept, modify, or reject any observation
- [ ] Override audit log (which observations were changed, by whom, when)
- [ ] Insufficient evidence reporting (explicit flag on under-evidenced dimensions)
- [ ] Report as read-only for reviewers until review is complete
- [ ] Frontend: report viewer, review interface, observation override UX

**Entry criteria**: Milestone 4 merged

**Exit criteria**:
- A human reviewer can view a report and accept/reject/modify any observation
- Every modification is logged
- Insufficient evidence dimensions produce explicit flags, not invented scores
- Reports are not forwarded to any external system without explicit reviewer action

---

## Milestone 6 — Zoom Feasibility Spike

**Goal**: Prove that the technical approach for Zoom integration is viable before investing in full implementation.

**Status**: Not Started

**Deliverables**:
- [ ] Meeting connector abstraction defined (join, leave, receive audio, send audio, mute, unmute, participant events, waiting-room state, health, reconnect, failure reporting)
- [ ] Zoom SDK or managed-provider evaluation (documented trade-offs)
- [ ] Prototype: bot joins a Zoom meeting as a visible named participant
- [ ] Two-way audio verified (bot receives audio from meeting; synthesised speech returned)
- [ ] Waiting-room handling verified
- [ ] Platform review requirements identified
- [ ] Risk register updated with actual findings from the spike
- [ ] Decision: proceed with Zoom integration or revise approach

**Entry criteria**: Milestone 4 merged; Zoom developer account and test credentials available

**Exit criteria**:
- A bot has joined a real Zoom meeting, received audio, and returned audio
- Waiting-room behavior is understood and handled
- All feasibility risks are documented with mitigations
- Go/no-go decision recorded in DECISIONS.md

---

## Milestone 7 — Zoom Integration

**Goal**: AI Role Agent joins live Zoom interviews as a disclosed, recruiter-controlled panelist.

**Status**: Not Started

**Deliverables**:
- [ ] Zoom connector implementation (MeetingConnector protocol)
- [ ] Bot identity: visible named participant ("ExpertSeat — AI Panelist"), static profile image
- [ ] Disclosed TTS: generated speech returned to the meeting (labeled AI, recruiter-controlled)
- [ ] Live transcription pipeline (speech-to-text from meeting audio)
- [ ] Transcript fed to Role Agent for context and question generation
- [ ] Recruiter activation control: agent joins muted; recruiter activates when ready
- [ ] Mute/unmute control from recruiter control room
- [ ] Recruiter takeover: deactivate agent at any moment
- [ ] Reconnection and failure reporting
- [ ] Interview intelligence layer contains no Zoom-specific reasoning
- [ ] End-to-end integration test (staging Zoom environment)

**Entry criteria**: Milestone 6 complete (feasibility spike accepted); Zoom app approved for use

**Exit criteria**:
- Bot joins a real Zoom meeting as a named, visible participant
- Recruiter controls activation, mute/unmute, and takeover
- Two-way audio works: bot hears meeting, meeting hears bot
- Failure and reconnection are reported to the recruiter control room
- No Zoom-specific code in the Role Agent or interview engine

---

## Milestone 8 — Live Recruiter Control Room

**Goal**: Recruiters have a real-time dashboard to monitor and control live Zoom interviews.

**Status**: Not Started

**Deliverables**:
- [ ] Live interview status view (active, waiting, complete)
- [ ] Real-time transcript display
- [ ] Agent state indicator (active, muted, queued question)
- [ ] One-click mute/unmute, activate/deactivate, takeover
- [ ] Queue management (upcoming questions visible)
- [ ] Reconnection alerts
- [ ] Incident log for the interview session

**Entry criteria**: Milestone 7 merged

**Exit criteria**:
- A recruiter can monitor and control a live Zoom interview from the control room
- Mute, activate, deactivate, and takeover all work in real time
- Reconnection events are surfaced without requiring recruiter action

---

## Milestone 9 — Candidate Comparison

**Goal**: Compare multiple candidates evaluated against the same Blueprint.

**Status**: Not Started

**Deliverables**:
- [ ] Side-by-side report comparison across candidates (same blueprint version)
- [ ] Cross-version comparison warning when blueprint versions differ
- [ ] Recruiter annotation on comparison view
- [ ] Comparison export (recruiter-facing only)

**Entry criteria**: Milestone 5 merged; at least two candidates with completed reports exist

**Exit criteria**:
- A recruiter can compare two or more candidates evaluated against the same Blueprint
- The UI clearly warns when blueprint versions differ
- No candidate data is accessible to other organizations

---

## Milestone 10 — Security and Reliability Hardening

**Goal**: Production-ready security posture and reliability standards before accepting real candidate data.

**Status**: Not Started

**Deliverables**:
- [ ] External penetration test, critical and high findings remediated
- [ ] Data protection impact assessment (DPIA)
- [ ] Threat model review
- [ ] Row-level security or equivalent for org isolation
- [ ] Encryption at rest and in transit verified
- [ ] Audit log completeness review
- [ ] Retention policy implemented per privacy/legal review
- [ ] Recording consent controls verified
- [ ] Dependency vulnerability scan passing
- [ ] SLO definitions documented
- [ ] Runbooks for common failure modes

**Entry criteria**: Milestones 7 and 9 merged; cloud environment provisioned

**Exit criteria**:
- External security review complete with all critical/high findings resolved
- DPIA complete
- All audit and retention controls active and tested

---

## Milestone 11 — Pilot Readiness

**Goal**: First paying organizations using the platform in production.

**Status**: Not Started

**Deliverables**:
- [ ] Onboarding flow for new organizations
- [ ] Support tooling (ticketing, status page)
- [ ] Terms of service and privacy policy published
- [ ] Billing integration
- [ ] SLA commitments documented
- [ ] Platform review approved (Zoom)

**Entry criteria**: Milestone 10 complete; legal review complete; platform review approved

**Exit criteria**:
- At least one pilot organization is onboarded and using the platform
- Billing is active
- Legal documents are published and accepted by users

---

## Items explicitly excluded from this roadmap

The following are not part of the committed milestone sequence. They may be evaluated as future phases after the pilot:

- Verified Blueprint marketplace
- Candidate portal
- ATS integrations (Lever, Greenhouse, Workday)
- Google Meet connector (out of scope for initial MVP)
- Kubernetes or container orchestration (infrastructure decision deferred)
- Webex connector (may follow after Zoom is stable; not committed)
