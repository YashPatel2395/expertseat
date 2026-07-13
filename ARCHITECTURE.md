# ExpertSeat — Architecture

**Status**: Milestone 0 — Foundation only
**Date**: 2026-07-13

This document describes both the current (implemented) state and the planned architecture. Sections are clearly labeled.

---

## Current State (Milestone 0 — Implemented)

The repository establishes a monorepo with two services and shared infrastructure:

```
expertseat/
├── apps/web/         Next.js 16 (App Router, React 19, TypeScript strict, Node.js 24)
├── services/api/     FastAPI (Python 3.12)
└── infrastructure/   Docker Compose (PostgreSQL 16, Redis 7)
```

**What is running:**
- Next.js app serves a single page with ExpertSeat branding
- FastAPI app exposes `/api/v1/health/live` and `/api/v1/health/ready` endpoints
- PostgreSQL and Redis are available via Docker Compose
- Alembic migration tooling is configured (no schema yet)

**What is not yet running:**
- No auth, no users, no organizations
- No interview or report logic
- No AI model integration
- No meeting connectors

---

## Planned Architecture (Milestone 1+)

The sections below describe the intended target architecture. Nothing described here is implemented.

### System Overview

```mermaid
graph TB
    subgraph Client
        WEB[Next.js Web App]
    end

    subgraph API Layer
        GW[API Gateway / FastAPI]
        AUTH[Auth Service]
        AGENT[Agent Orchestrator]
        REPORT[Report Generator]
    end

    subgraph Data Layer
        PG[(PostgreSQL)]
        REDIS[(Redis)]
        S3[(Object Storage)]
    end

    subgraph External
        AI[AI Provider Abstraction]
        MEET[Meeting Connector Abstraction]
        EMAIL[Email / Notification]
    end

    WEB --> GW
    GW --> AUTH
    GW --> AGENT
    GW --> REPORT
    AUTH --> PG
    AGENT --> PG
    AGENT --> REDIS
    AGENT --> AI
    AGENT --> MEET
    REPORT --> PG
    REPORT --> S3
    GW --> EMAIL
```

### Entity Model (Planned)

```mermaid
erDiagram
    Organization ||--o{ User : has
    Organization ||--o{ Blueprint : owns
    Organization ||--o{ Candidate : manages
    Blueprint ||--o{ Interview : used_in
    Candidate ||--o{ Interview : participates_in
    Interview ||--|| ConsentRecord : requires
    Interview ||--o{ InterviewEvent : produces
    Interview ||--|| Report : generates
    Report ||--o{ Observation : contains
    Report ||--o{ ObservationReview : reviewed_via
    User ||--o{ ObservationReview : performs
```

**Entity groups and planned milestones:**

| Entity Group | Planned Milestone |
|---|---|
| Organization, User, AuditLog | Milestone 1 |
| Blueprint, BlueprintVersion, EvidenceDocument | Milestone 2 |
| Candidate, ConsentRecord | Milestone 3 |
| Interview, InterviewLifecycleEvent | Milestone 3 |
| InterviewEvent, AgentObservation | Milestone 4 |
| Report, Observation, ObservationReview | Milestone 5 |
| MeetingSession (video/audio) | Milestone 7 |

---

### API Structure (Planned)

All endpoints are under `/api/v1/`.

| Router | Endpoints | Milestone |
|---|---|---|
| `/health` | `GET /live`, `GET /ready` | 0 (done) |
| `/auth` | `POST /login`, `POST /logout`, `POST /refresh` | 1 |
| `/orgs` | CRUD for organizations | 1 |
| `/users` | CRUD for users within org | 1 |
| `/blueprints` | CRUD + versioning | 2 |
| `/candidates` | CRUD, consent management | 2 |
| `/interviews` | Schedule, start, end | 3 |
| `/interviews/{id}/agent` | Agent interaction endpoints | 3 |
| `/reports` | Report retrieval, review | 3 |

---

### AI Provider Abstraction (Planned, Milestone 4)

The system is designed to avoid lock-in to a single AI provider. All model calls go through a provider abstraction layer:

```python
# Planned interface — not yet implemented
class AIProvider(Protocol):
    async def complete(self, prompt: str, context: InterviewContext) -> AgentResponse: ...
    async def embed(self, text: str) -> list[float]: ...
```

Planned initial support: configurable at Milestone 4 — specific provider and models to be selected based on capability and pricing at that time. The abstraction allows swapping providers per Blueprint or per org.

---

### Meeting Connector Abstraction (Contract: Milestone 6, Implementation: Milestone 7)

Video interview integration is abstracted behind a connector interface. The connector contract is defined in Milestone 6 (Zoom feasibility spike); the first implementation ships in Milestone 7 (Zoom integration). The interview intelligence layer must not contain any platform-specific reasoning — all Zoom, Webex, or other platform specifics belong inside the connector, not the agent.

```python
# Planned interface — not yet implemented
# All operations must be implementable for any supported meeting platform.
class MeetingConnector(Protocol):
    async def join(self, session_id: str, agent_identity: AgentIdentity) -> MeetingSession: ...
    async def leave(self, session: MeetingSession) -> None: ...
    async def receive_audio(self, session: MeetingSession) -> AsyncIterator[AudioChunk]: ...
    async def send_audio(self, session: MeetingSession, audio: AudioChunk) -> None: ...
    async def mute(self, session: MeetingSession) -> None: ...
    async def unmute(self, session: MeetingSession) -> None: ...
    async def participant_events(self, session: MeetingSession) -> AsyncIterator[ParticipantEvent]: ...
    async def waiting_room_state(self, session: MeetingSession) -> WaitingRoomState: ...
    async def health(self, session: MeetingSession) -> ConnectorHealth: ...
    async def reconnect(self, session: MeetingSession) -> MeetingSession: ...
    async def report_failure(self, session: MeetingSession, error: Exception) -> None: ...
```

Platform order (see ADR-021):
- **Zoom** — first connector; feasibility spike in Milestone 6, implementation in Milestone 7
- **Webex** — possible follow-on after Zoom is stable in production; not committed
- **Google Meet** — explicitly out of scope for the initial MVP; will not be implemented in the committed milestone sequence

The Role Agent joins as a disclosed, named participant and uses TTS to participate verbally (see ADR-020). A static profile image is used — no generated video avatar.

---

### Evidence Pipeline (Planned, Milestone 2–3)

```mermaid
sequenceDiagram
    participant R as Recruiter
    participant API as API
    participant EP as Evidence Processor
    participant VS as Vector Store
    participant Agent as Role Agent

    R->>API: Upload JD + Reference Material
    API->>EP: Process documents
    EP->>VS: Embed + store chunks
    Note over VS: Indexed by Blueprint ID

    R->>API: Start Interview
    API->>Agent: Initialize with Blueprint + Candidate context
    Agent->>VS: Query relevant evidence
    VS->>Agent: Relevant chunks
    Agent->>API: Evidence-backed question
```

---

### Org Isolation

All database rows are scoped to an `organization_id`. Every query at the API layer includes an org filter derived from the authenticated user's JWT claims. Cross-org data access is prevented at the query layer, not just the API layer.

Planned implementation:
- Row-level security (RLS) policies in PostgreSQL for defense-in-depth
- Application-level org filter on every repository query
- Audit logging for any cross-org access attempt

---

### Deployment (Planned, Milestone 9)

Target: **Modular monolith** on a major cloud provider (provider TBD), backed by managed services. The container orchestration approach (serverless containers, managed container services, or otherwise) is deferred to Milestone 9 when the actual infrastructure requirements are understood.

The application is structured as a modular monolith: a single deployable FastAPI service with clearly bounded internal modules (auth, blueprints, interviews, reports, meeting connectors). Modules communicate in-process, not over the network, until there is a demonstrated need to extract a service.

```mermaid
graph LR
    subgraph Cloud Platform
        ING[Load Balancer / TLS]
        WEB_SVC[Next.js (managed hosting)]
        API_SVC[FastAPI (containerized)]
    end

    subgraph Managed Services
        PG[(Managed PostgreSQL)]
        REDIS[(Managed Redis)]
        S3_STORE[(Object Storage)]
    end

    ING --> WEB_SVC
    ING --> API_SVC
    API_SVC --> PG
    API_SVC --> REDIS
    API_SVC --> S3_STORE
```

**Rationale**: Kubernetes adds significant operational overhead and is premature for an early-stage product. Managed services (RDS, ElastiCache, S3-compatible storage) provide reliability and scaling without requiring a cluster. The decision to adopt container orchestration is deferred to when scale or operational requirements justify it.

---

## Key Technology Decisions

See [DECISIONS.md](./DECISIONS.md) for full context on each decision.

| Decision | Choice | Status |
|---|---|---|
| Frontend framework | Next.js 16 (App Router, React 19, Node.js 24) | Decided |
| Backend framework | FastAPI (Python 3.12) | Decided |
| ORM | SQLAlchemy 2.0 | Decided |
| Database | PostgreSQL 16 | Decided |
| Cache / queue | Redis 7 | Decided |
| Package manager (FE) | pnpm | Decided |
| Package manager (BE) | uv | Decided |
| Monorepo tooling | Simple scripts (no turborepo yet) | Decided |
| Auth approach | JWT + session tokens | Planned |
| AI provider | Abstracted (provider selected at Milestone 4) | Planned |
| Meeting connector | Abstracted (Zoom: feasibility M6, implementation M7) | Planned |
| Deployment platform | Modular monolith + managed services (orchestration TBD at M9) | Planned |
