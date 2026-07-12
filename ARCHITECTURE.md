# ExpertSeat — Architecture

**Status**: Milestone 0 — Foundation only
**Date**: 2026-07-12

This document describes both the current (implemented) state and the planned architecture. Sections are clearly labeled.

---

## Current State (Milestone 0 — Implemented)

The repository establishes a monorepo with two services and shared infrastructure:

```
expertseat/
├── apps/web/         Next.js 14 (App Router, TypeScript strict)
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
| Organization, User | Milestone 1 |
| Blueprint, BlueprintVersion | Milestone 2 |
| Candidate, ConsentRecord | Milestone 2 |
| Interview, InterviewEvent | Milestone 3 |
| Report, Observation, ObservationReview | Milestone 3 |
| MeetingSession (video/audio) | Milestone 5 |
| AuditLog | Milestone 1 |

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

### AI Provider Abstraction (Planned, Milestone 3)

The system is designed to avoid lock-in to a single AI provider. All model calls go through a provider abstraction layer:

```python
# Planned interface — not yet implemented
class AIProvider(Protocol):
    async def complete(self, prompt: str, context: InterviewContext) -> AgentResponse: ...
    async def embed(self, text: str) -> list[float]: ...
```

Planned initial support: OpenAI GPT-4o, Anthropic Claude. The abstraction allows swapping providers per Blueprint or per org.

---

### Meeting Connector Abstraction (Planned, Milestone 5)

Video interview integration is abstracted behind a connector interface:

```python
# Planned interface — not yet implemented
class MeetingConnector(Protocol):
    async def join(self, session_id: str, agent_identity: AgentIdentity) -> MeetingSession: ...
    async def send_message(self, session: MeetingSession, text: str) -> None: ...
    async def leave(self, session: MeetingSession) -> None: ...
```

Planned connectors: Zoom (Milestone 5), Google Meet (Milestone 6). The agent participates as a named bot user — always disclosed as an AI system.

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

Target: Kubernetes on a major cloud provider (provider TBD).

```mermaid
graph LR
    subgraph K8s Cluster
        ING[Ingress / TLS]
        WEB_DEP[web Deployment]
        API_DEP[api Deployment]
        WORKER[agent-worker Deployment]
    end

    subgraph Managed Services
        RDS[(RDS PostgreSQL)]
        ELASTICACHE[(ElastiCache Redis)]
        S3_STORE[(S3 / Object Storage)]
    end

    ING --> WEB_DEP
    ING --> API_DEP
    API_DEP --> WORKER
    API_DEP --> RDS
    API_DEP --> ELASTICACHE
    WORKER --> S3_STORE
```

---

## Key Technology Decisions

See [DECISIONS.md](./DECISIONS.md) for full context on each decision.

| Decision | Choice | Status |
|---|---|---|
| Frontend framework | Next.js 14 (App Router) | Decided |
| Backend framework | FastAPI (Python 3.12) | Decided |
| ORM | SQLAlchemy 2.0 | Decided |
| Database | PostgreSQL 16 | Decided |
| Cache / queue | Redis 7 | Decided |
| Package manager (FE) | pnpm | Decided |
| Package manager (BE) | uv | Decided |
| Monorepo tooling | Simple scripts (no turborepo yet) | Decided |
| Auth approach | JWT + session tokens | Planned |
| AI provider | Abstracted (OpenAI first) | Planned |
| Meeting connector | Abstracted (Zoom first) | Planned |
| Deployment platform | Kubernetes (provider TBD) | Planned |
