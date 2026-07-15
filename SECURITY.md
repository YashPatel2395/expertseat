# ExpertSeat — Security

**Status**: Milestone 0 — Foundation (Round 2 audit remediation 2026-07-13)
**Date**: 2026-07-13

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
- **Repository is currently public** (changed from private on 2026-07-13 per owner decision; see DECISIONS.md)
- Root `pnpm-lock.yaml` and `services/api/uv.lock` lock all dependency versions
- Dependabot is configured for automated dependency update PRs (npm and pip)
- CI uses least-privilege permissions (`contents: read` at workflow level)
- No secrets are hardcoded anywhere in the codebase
- Gitleaks runs against full git history on every PR and push in CI (secret detection — not CVE scanning)
- `pip-audit` and `pnpm audit --audit-level high` run in CI for dependency CVE scanning (separate from Gitleaks)
- Docker development ports bound to `127.0.0.1` only (not exposed on all interfaces)
- GitHub Actions pinned to immutable commit SHAs (Node.js 24 runtime; no Node.js 20 deprecation warnings)
- `uv` version pinned in CI (`0.11.7`) for reproducible installs
- Structured logging configured: JSON output in production, console output in development
- Exception handler logs exception type only — never `str(exc)` which may contain sensitive data
- Request ID middleware: UUID per request, bound to log context, returned in `X-Request-ID` header
- Environment config resolves `.env` relative to repo root (not CWD) — deterministic across all invocation contexts
- Health-check connection timeouts are bounded and configurable (no unbounded OS-level TCP timeouts)
- Branch protection configured on `main` (verified 2026-07-13 via GitHub API):
  - Required status checks (strict — branch must be up-to-date): Secret scan (Gitleaks), Validate Docker Compose configuration, Frontend (format, lint, typecheck, test, build), Backend (format, lint, typecheck, test), Database migrations (upgrade → downgrade → upgrade), Dependency vulnerability audit, API runtime smoke test
  - No force pushes allowed
  - No direct pushes allowed (enforce_admins: true)
  - No branch deletion allowed

### Known gaps at Milestone 0

- **GitHub Advanced Security (GHAS)**: Not available at current plan tier. Dependency Review workflow was removed because it permanently failed without GHAS. `pip-audit` + `pnpm audit` cover CVE scanning; Gitleaks covers secret detection.
- **Secret scanning by GitHub**: Not enabled (requires GHAS). Gitleaks in CI covers this gap.

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

## Authentication (Implemented, Milestone 1)

- JWT access tokens (10-minute TTL) delivered via `es_access` HttpOnly cookie only — never in JSON response body
- Opaque refresh tokens (14-day TTL) delivered via `es_refresh` HttpOnly cookie — SHA-256 hash stored; raw token never persisted
- CSRF protection via double-submit cookie pattern (`es_csrf`, non-HttpOnly) required on all authenticated state-mutating endpoints including refresh, logout, logout-all, switch-org, and invitation accept
- Refresh tokens rotated on every use with `SELECT FOR UPDATE` to prevent TOCTOU races
- Replay detection: replaying a rotated token revokes the entire session family (family-based revocation)
- Email verification required before login; 64-char hex token (256-bit entropy) sent via link, not 6-digit code
- Password minimum 12 characters, maximum 128 characters (unicode supported)
- Passwords hashed with Argon2id (memory cost 64 MiB, time cost 3, parallelism 1)
- Rate limiting on auth endpoints (10 req/60s per client IP); IP pseudonymized via HMAC-SHA256 before use as Redis key
- Fail-closed rate limiting: Redis unavailable → 503 (not bypass)
- Password reset tokens: 256-bit entropy, 30-minute TTL, SHA-256 hash stored; issuing a new token invalidates all prior unused tokens

---

## Authorization (Implemented, Milestone 1)

- Role-based access control: `admin`, `recruiter`, `reviewer` (org-level workspace roles)
- **DB-backed authorization on every request**: `get_current_user()` validates session (not revoked, not expired), user (active, email verified), membership (active, user and org match), and organization (active) — role derived from DB Membership row, never from JWT claim
- JWT `org`, `mid`, and `role` claims serve as routing identifiers for DB lookups only
- Revoked sessions, disabled users, deactivated memberships, and role changes take effect on the next request (no JWT-expiry delay)
- Last-admin protection: demoting or disabling the last admin of an org is rejected (409 LAST_ADMIN_PROTECTED); enforced with `SELECT FOR UPDATE` to prevent concurrent bypass
- All workspace-scoped queries receive `org_id` from DB-validated context — never from request body or path parameters

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
- Data retention is configurable per org (retention period is a legal/privacy review decision — no default is committed here)
- Candidates can request data deletion (DSAR workflow, Milestone 10)
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

## Prompt Injection (Planned, Milestone 4)

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

Interview recordings (when meeting connectors are implemented, Milestone 7):
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

The repository is currently public. If you discover a security issue, please open a private security advisory via the GitHub Security tab rather than a public issue, or contact the repository owner directly.

---

## Compliance Considerations

The following regulations may apply to ExpertSeat when operational:

- **GDPR / UK GDPR**: Applies if processing EU/UK candidate data
- **CCPA**: Applies if processing California resident data
- **EU AI Act**: May apply to AI-assisted hiring (high-risk AI system classification under review)
- **EEOC / employment law**: Varies by jurisdiction; AI in hiring is regulated in some US states and cities (NYC Local Law 144, Illinois AEIA, etc.)

**Current state**: No candidate data is processed. Compliance review is planned for Milestone 10.

We are not currently compliant with any of the above — we have no production system yet.
