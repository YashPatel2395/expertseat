# ExpertSeat — Security

**Status**: Milestone 0 — Foundation
**Date**: 2026-07-12

This document distinguishes between current security measures (implemented) and planned security measures (not yet implemented).

---

## Principles

1. **Defense in depth**: No single control is relied upon. Multiple layers protect each sensitive operation.
2. **Least privilege**: Services and users have only the access they need.
3. **Fail closed**: When in doubt, deny access. Errors do not grant permissions.
4. **No secrets in code**: Secrets are never committed to the repository.
5. **Audit everything**: Security-relevant events are logged with enough context to investigate.
6. **Candidate data sensitivity**: Candidate data is treated as highly sensitive personal information.

---

## Current State (Milestone 0)

### Implemented

- `.gitignore` prevents `.env` files from being committed
- `.env.example` contains only safe placeholder values
- GitHub repository is private
- Dependencies are managed with lock files (pnpm lockfile, uv.lock)
- Dependabot is configured for automated dependency vulnerability alerts
- CI uses least-privilege permissions (`contents: read`)
- No secrets are hardcoded anywhere in the codebase

### Not Yet Implemented

Everything in the sections below is planned but not implemented.

---

## Secret Handling

**Planned implementation** (Milestone 1):

- All secrets are loaded from environment variables
- No secrets in code, config files, or Docker images
- Development secrets use `.env` (gitignored)
- Production secrets use a secrets manager (AWS Secrets Manager or Vault)
- Secret rotation procedure documented in runbooks
- CI secrets stored in GitHub repository secrets (not in workflow files)

**Current state**: No secrets exist yet (no auth, no API keys).

---

## Authentication (Planned, Milestone 1)

- JWT access tokens (short TTL: 15 minutes)
- Refresh tokens stored in Redis with TTL (7 days)
- Refresh tokens are rotated on each use
- Tokens are invalidated on logout
- Passwords hashed with bcrypt (minimum cost factor 12)
- Rate limiting on login endpoint
- No "remember me" option for initial release (security posture over convenience)

---

## Authorization (Planned, Milestone 1)

- Role-based access control: `recruiter`, `org_admin`, `superadmin`
- All API endpoints require authentication except `/health/*`
- All data queries include `organization_id` filter (enforced at repository layer)
- PostgreSQL row-level security as defense-in-depth layer
- No cross-org data access ever returned (even with valid JWT)

---

## Org Isolation (Planned, Milestone 1)

Org isolation is a critical security control. See [DECISIONS.md ADR-015](./DECISIONS.md).

- All database tables include `organization_id` foreign key
- All queries filtered by org at application layer
- RLS policies in PostgreSQL for defense-in-depth
- Integration tests specifically verify org boundary enforcement
- Any org isolation violation is treated as a severity-1 incident

---

## Candidate Data Sensitivity

Candidate data (name, contact, interview responses, assessments) is treated as Category 1 sensitive personal information.

**Planned controls** (Milestone 2+):
- Candidates are referenced by UUID internally
- PII fields are encrypted at rest where possible
- Candidate data is strictly isolated to the hiring organization
- Data retention is configurable per org (default: 2 years)
- Candidates can request data deletion (DSAR workflow, Milestone 7)
- Interview recordings (if any) require explicit multi-party consent

---

## File Upload Security (Planned, Milestone 2)

Blueprint evidence documents are uploaded by recruiters. Risks include:
- Malicious file content (macros, embedded scripts)
- Oversized uploads causing storage abuse
- Content type spoofing

**Planned controls**:
- File type allow-list (PDF, DOCX, TXT, MD only)
- Content type validated server-side (not just MIME header)
- File size limits enforced at API layer
- Files scanned with ClamAV or equivalent before processing
- Files stored in object storage (not on application servers)
- Files not served directly to browsers (signed URLs with TTL)

---

## Prompt Injection (Planned, Milestone 3)

AI Role Agents receive input from multiple sources: blueprints (recruiter-controlled), reference documents (recruiter-uploaded), and candidate responses (untrusted). Prompt injection is a real risk.

**Planned mitigations**:
- Blueprint content sanitized before insertion into prompts
- Candidate input treated as untrusted and wrapped in structural separators
- Agent instructions include explicit rejection of instructions embedded in content
- AI output validated against expected structure before use
- Unusual agent behavior (e.g., output not matching report schema) triggers review flag
- No agent output is executed as code

---

## Encryption

**Current state**: No encryption configured yet (no production environment).

**Planned**:
- TLS 1.2+ required for all external connections (enforced at ingress)
- Database connections use SSL
- Redis connections use TLS in production
- Sensitive fields encrypted at rest in database (application-layer encryption for PII)
- Object storage uses SSE (server-side encryption)

---

## Audit Logging (Planned, Milestone 1)

Security-relevant events must be logged with: timestamp, event type, actor (user_id, org_id), target, outcome (success/failure), IP address.

**Events to log**:
- Login (success, failure, lockout)
- Token refresh
- Logout
- Org member additions/removals
- Blueprint creation, modification, deletion
- Interview start, end
- Consent delivery, acceptance, rejection
- Report access
- Data export requests
- Admin actions

Audit logs are append-only and not modifiable by application users.

---

## Recording Controls

Interview recordings (when meeting connectors are implemented, Milestone 5):
- Opt-in only — no default recording
- Requires consent from all parties (recruiter, all human panelists, candidate)
- Consent is recorded before recording starts
- Recording stops immediately on any party request
- Recordings are stored encrypted with TTL
- Recordings are never used for AI model training without explicit multi-party consent

---

## Vulnerability Reporting

We have not yet published a vulnerability disclosure policy. When the platform launches (Milestone 11), the following will apply:

- Security vulnerabilities should be reported to: `security@[domain TBD]`
- Do not file public issues for security vulnerabilities
- Response commitment: acknowledge within 48 hours
- We will work with reporters to understand and fix issues before public disclosure
- We will credit reporters (with their permission)

For Milestone 0, the repository is private. If you discover a security issue, contact the repository owner directly.

---

## Compliance Considerations

The following regulations may apply to ExpertSeat when operational:

- **GDPR / UK GDPR**: Applies if processing EU/UK candidate data
- **CCPA**: Applies if processing California resident data
- **EU AI Act**: May apply to AI-assisted hiring (high-risk AI system classification under review)
- **EEOC / employment law**: Varies by jurisdiction; AI in hiring is regulated in some US states and cities (NYC Local Law 144, Illinois AEIA, etc.)

**Current state**: No candidate data is processed. Compliance review is planned for Milestone 10.

We are not currently compliant with any of the above — we have no production system yet.
