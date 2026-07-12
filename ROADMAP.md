# ExpertSeat — Roadmap

**Last Updated**: 2026-07-12

Milestones are sequential. Each has entry criteria (what must be true before it starts) and exit criteria (what must be true before the next milestone begins).

---

## Milestone 0 — Production Foundation

**Goal**: Establish a production-grade repository with CI, infrastructure, and documentation. No product features.

**Status**: In Progress

**Deliverables**:
- [x] Private GitHub repository with branch protection
- [x] Next.js 14 frontend (branding only)
- [x] FastAPI backend with health endpoints
- [x] PostgreSQL + Redis via Docker Compose
- [x] Alembic migration tooling configured
- [x] GitHub Actions CI (lint, typecheck, test, build)
- [x] Dependabot for npm and pip
- [x] Comprehensive documentation
- [x] All quality gates passing

**Entry criteria**: None (first milestone)

**Exit criteria**:
- CI passing on `milestone/0-foundation`
- PR to `main` created
- All documentation reviewed and accurate

---

## Milestone 1 — Auth and Organizations

**Goal**: Implement organization accounts, user accounts, and authentication.

**Status**: Not Started

**Deliverables**:
- [ ] Organization CRUD (name, slug, settings)
- [ ] User CRUD (email, role: recruiter/admin)
- [ ] JWT authentication (login, logout, token refresh)
- [ ] Role-based access control (recruiter, org-admin, superadmin)
- [ ] Org isolation enforcement (all queries scoped to org)
- [ ] Audit log for auth events
- [ ] Frontend: login page, org switcher, user settings
- [ ] Initial database migrations (organizations, users, audit_logs tables)

**Entry criteria**: Milestone 0 merged to main

**Exit criteria**:
- A recruiter can create an account, log in, and log out
- Org isolation tests pass
- Auth endpoints documented in API spec

---

## Milestone 2 — Blueprints and Candidates

**Goal**: Implement Blueprint creation/versioning and candidate record management.

**Status**: Not Started

**Deliverables**:
- [ ] Blueprint CRUD with versioning
- [ ] Evidence upload (job description, reference documents)
- [ ] Evidence processing (chunking, embedding)
- [ ] Blueprint configuration (evaluation dimensions, rubrics, question bank)
- [ ] Candidate CRUD (name, contact, linked submissions)
- [ ] Consent record management (template, delivery, record)
- [ ] Frontend: Blueprint builder, candidate list, consent template editor
- [ ] Database migrations for blueprints, blueprint_versions, candidates, consent_records

**Entry criteria**: Milestone 1 merged

**Exit criteria**:
- A recruiter can create a Blueprint, upload reference material, and view a candidate record
- Consent template can be configured and previewed
- Evidence processing pipeline tested end-to-end

---

## Milestone 3 — Interview MVP

**Goal**: End-to-end interview flow with text-based Role Agent participation.

**Status**: Not Started

**Deliverables**:
- [ ] Interview scheduling (associate blueprint + candidate + time)
- [ ] Candidate consent delivery and recording
- [ ] Live interview room (text-based, browser)
- [ ] Role Agent question generation from blueprint + evidence
- [ ] Role Agent response handling and follow-up logic
- [ ] Post-interview report generation
- [ ] Structured report: observations, scores, evidence citations
- [ ] Human review workflow (accept/modify/reject observations)
- [ ] Frontend: interview room, report viewer, review interface
- [ ] AI provider abstraction layer (OpenAI GPT-4o initial provider)
- [ ] Database migrations for interviews, interview_events, reports, observations

**Entry criteria**: Milestone 2 merged, AI provider API key available

**Exit criteria**:
- Full interview flow works end-to-end in staging environment
- Report is generated with evidence citations
- Human reviewer can accept/reject observations
- All quality gates passing

---

## Milestone 4 — Verified Blueprint Library

**Goal**: Shared library of org-agnostic blueprints reviewed against a quality rubric.

**Status**: Not Started

**Deliverables**:
- [ ] Blueprint quality rubric (documented + encoded as checklist)
- [ ] Blueprint submission workflow for verification review
- [ ] Verified Blueprint library (browseable, filterable)
- [ ] Blueprint forking (copy verified blueprint into org)
- [ ] Verification status indicator on all blueprints
- [ ] Internal admin tooling for verification review

**Entry criteria**: Milestone 3 merged

**Exit criteria**:
- At least 5 verified blueprints available in the library
- Fork-to-org workflow tested

---

## Milestone 5 — Meeting Connector (Video)

**Goal**: AI panelist can join live video interviews as a disclosed bot participant.

**Status**: Not Started

**Deliverables**:
- [ ] Meeting connector abstraction layer
- [ ] Zoom connector implementation
- [ ] Bot identity configuration (name, avatar, disclosure banner)
- [ ] Real-time transcription (speech-to-text pipeline)
- [ ] Agent reads transcript and queues questions
- [ ] Agent can deliver questions as text in meeting chat
- [ ] Recording controls (opt-in, consent required)
- [ ] Frontend: meeting link configuration, live interview monitor

**Entry criteria**: Milestone 3 merged, Zoom app credentials available

**Exit criteria**:
- Bot joins and leaves Zoom meeting programmatically
- Transcript is captured and fed to agent
- Agent questions appear in meeting chat
- Recording only starts with explicit consent

---

## Milestone 6 — Multi-Panelist Collaboration

**Goal**: Multiple human and AI panelists can participate in the same interview with coordinated scoring.

**Status**: Not Started

**Deliverables**:
- [ ] Multi-panelist interview configuration
- [ ] Panelist question queue (avoid duplication)
- [ ] Per-panelist observation capture
- [ ] Collaborative report (merge observations from multiple panelists)
- [ ] Google Meet connector
- [ ] Panelist coordination protocol

**Entry criteria**: Milestone 5 merged

---

## Milestone 7 — Candidate Portal

**Goal**: Candidates can view their consent records and (optionally) their interview reports.

**Status**: Not Started

**Deliverables**:
- [ ] Candidate authentication (separate from recruiter auth)
- [ ] Consent record access
- [ ] Report access (org-configurable: share or not)
- [ ] Data subject access request (DSAR) workflow
- [ ] Candidate data deletion request workflow

**Entry criteria**: Milestone 3 merged

---

## Milestone 8 — ATS Integrations

**Goal**: Reports can be pushed to ATS systems (Lever, Greenhouse, Workday).

**Status**: Not Started

**Deliverables**:
- [ ] ATS connector abstraction
- [ ] Lever integration
- [ ] Greenhouse integration
- [ ] Configurable report-to-ATS field mapping
- [ ] Sync status tracking

**Entry criteria**: Milestone 3 merged

---

## Milestone 9 — Production Deployment

**Goal**: Platform running in a managed Kubernetes environment with monitoring, alerting, and SLOs.

**Status**: Not Started

**Deliverables**:
- [ ] Kubernetes manifests (Helm charts or Kustomize)
- [ ] CI/CD pipeline with staging and production environments
- [ ] Managed database (RDS or equivalent)
- [ ] Managed Redis (ElastiCache or equivalent)
- [ ] Observability: logs, metrics, traces (OpenTelemetry)
- [ ] Alerting (PagerDuty or equivalent)
- [ ] SLO definitions (uptime, latency)
- [ ] Runbooks for common failure modes

**Entry criteria**: Milestone 3 merged, cloud environment provisioned

---

## Milestone 10 — Security Audit

**Goal**: External security review before any production traffic with real candidate data.

**Status**: Not Started

**Deliverables**:
- [ ] Threat model review
- [ ] Penetration test (external vendor)
- [ ] Remediation of all critical and high findings
- [ ] Data protection impact assessment (DPIA)
- [ ] Privacy policy reviewed by counsel

**Entry criteria**: Milestone 9 merged

---

## Milestone 11 — Pilot Launch

**Goal**: First paying organizations using the platform in production.

**Status**: Not Started

**Deliverables**:
- [ ] Onboarding flow for new organizations
- [ ] Support tooling (ticketing, status page)
- [ ] Terms of service and privacy policy published
- [ ] Billing integration
- [ ] SLA commitments documented

**Entry criteria**: Milestone 10 complete, legal review complete
