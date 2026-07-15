# ExpertSeat — Milestone 1 Plan: Authentication and Company Workspace

**Status**: Planning  
**Branch**: `milestone/1-auth-workspace`  
**Base commit**: `23ddc35` (Milestone 0 Audit Remediation, merged to main)  
**Date**: 2026-07-13

---

## 1. Repository State at Milestone 1 Start

### Backend (`services/api/`)

| File | State |
|---|---|
| `app/main.py` | FastAPI app, RequestIDMiddleware, CORSMiddleware, generic exception handler |
| `app/config.py` | Pydantic Settings: app_env, debug, database_url, redis_url, api_v1_prefix, cors_allowed_origins, db timeouts |
| `app/database.py` | Sync SQLAlchemy engine + SessionLocal + Base + get_db() + check_database_connection() |
| `app/routers/health.py` | GET /api/v1/health/live, GET /api/v1/health/ready |
| `app/models/__init__.py` | Empty |
| `alembic/versions/0001_initial.py` | No-op placeholder |
| `pyproject.toml` | fastapi, uvicorn, sqlalchemy, alembic, psycopg2-binary, pydantic, pydantic-settings, structlog, redis |

**Missing dependencies** (to be added): argon2-cffi, pyjwt

### Frontend (`apps/web/`)

| File | State |
|---|---|
| `src/app/page.tsx` | Single home page with "Foundation development" label |
| `package.json` | next 16.2.10, react 19.2.7, tailwind, vitest, @testing-library/react |

**Missing packages** (to be added): @playwright/test

### Infrastructure (`infrastructure/`)

| Service | State |
|---|---|
| PostgreSQL 16 | Running on 127.0.0.1:5432 |
| Redis 7 | Running on 127.0.0.1:6379 |
| Mailpit | Not yet added |

### CI/Scripts

- 7 required status check contexts on `main`
- Leaf script architecture: check_compose, check_frontend, check_backend, check_migrations, check_secrets, check_dependencies, check_runtime
- `scripts/check_auth_integration.sh` — does not exist yet
- `scripts/check_e2e.sh` — does not exist yet

---

## 2. Milestone Scope

Milestone 1 delivers a production-ready multi-tenant authentication and company workspace system. Every security-critical path is tested with real dependencies (no mocks for auth).

### Authentication flows
- Account registration with email verification (6-digit code, 24-hour TTL)
- Login (email + password, returns access + refresh tokens via HttpOnly cookies)
- Token refresh (opaque refresh token rotation, family revocation on reuse)
- Logout (single session) and logout-all (all sessions)
- Password reset (email link, 1-hour TTL, single-use token)
- Password change (authenticated, requires current password)
- Session listing and management (view and revoke active sessions)

### Workspace (organization) flows
- Organization creation (first user becomes admin)
- Workspace switching (user belongs to multiple orgs)
- Member listing and role display
- Member invitation by email (pending invitation, accept via email link)
- RBAC: admin, recruiter, reviewer roles
- Role assignment (admin only)
- Last-admin protection (transactional check before demotion/removal)
- Member disabling and reactivation (admin only)
- Organization settings update (name, slug — admin only)
- Immutable audit log (append-only, admin read-only)

### Security controls
- Argon2id password hashing (time_cost=2, memory_cost=65536, parallelism=2)
- JWT access tokens (HS256, 10 min, signed with SECRET_KEY)
- Opaque refresh tokens (32 random bytes = 256-bit entropy, SHA-256 hash stored in DB)
- HttpOnly + Secure(prod) + SameSite=Lax cookies for access and refresh tokens
- Refresh cookie path restricted to `/api/v1/auth` (prevents accidental exposure)
- Non-HttpOnly CSRF cookie + X-CSRF-Token double-submit pattern
- Origin header validation on all state-mutating endpoints
- Redis-backed rate limiting on all auth endpoints (fixed-window, fail-closed)
- Refresh token family tracking + reuse detection → full family revocation

---

## 3. Explicit Exclusions

The following are explicitly **not** in scope for Milestone 1:

- OAuth / SSO / SAML (planned Milestone 6)
- MFA / TOTP (planned Milestone 6)
- Zoom or calendar integrations (Milestone 6–7)
- Interview Blueprint, Candidate, or Report entities (Milestone 2+)
- AI / Role Agent (Milestone 4+)
- Billing / subscription management (Milestone 8)
- Admin super-user panel (Milestone 8)
- End-to-end email delivery testing against a real SMTP provider (Mailpit is the dev target)
- CDN or file upload (not needed until resume/evidence uploads in Milestone 3)
- WebSocket or real-time features

---

## 4. Data Model

### 4.1 Tables

**`users`**
```
id              UUID          PK, default gen_random_uuid()
email           TEXT          NOT NULL, UNIQUE
email_verified  BOOLEAN       NOT NULL DEFAULT FALSE
hashed_password TEXT          NOT NULL
full_name       TEXT          NOT NULL
is_active       BOOLEAN       NOT NULL DEFAULT TRUE
created_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
```

**`organizations`**
```
id          UUID        PK, default gen_random_uuid()
name        TEXT        NOT NULL
slug        TEXT        NOT NULL, UNIQUE
is_active   BOOLEAN     NOT NULL DEFAULT TRUE
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
```
Slug: lowercase, alphanumeric + hyphens, 3–48 chars, derived from name at creation, mutable by admin.

**`memberships`**
```
id          UUID        PK, default gen_random_uuid()
user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE
org_id      UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE
role        TEXT        NOT NULL CHECK (role IN ('admin','recruiter','reviewer'))
is_active   BOOLEAN     NOT NULL DEFAULT TRUE
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE (user_id, org_id)
```

**`auth_sessions`**
```
id                  UUID        PK, default gen_random_uuid()
user_id             UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE
org_id              UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE
membership_id       UUID        NOT NULL REFERENCES memberships(id) ON DELETE CASCADE
refresh_token_hash  TEXT        NOT NULL, UNIQUE
family_id           UUID        NOT NULL
ip_address_hash     TEXT        NOT NULL
user_agent          TEXT
last_used_at        TIMESTAMPTZ NOT NULL DEFAULT now()
expires_at          TIMESTAMPTZ NOT NULL
revoked_at          TIMESTAMPTZ
created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
```
`family_id`: shared across all rotations of the same refresh token lineage. On reuse detection, all sessions with this `family_id` are revoked.

**`email_verification_tokens`**
```
id          UUID        PK, default gen_random_uuid()
user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE
code        TEXT        NOT NULL        -- 6-digit code, hashed with SHA-256
expires_at  TIMESTAMPTZ NOT NULL
used_at     TIMESTAMPTZ
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
```

**`password_reset_tokens`**
```
id          UUID        PK, default gen_random_uuid()
user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE
token_hash  TEXT        NOT NULL, UNIQUE    -- SHA-256 of 32-byte random token
expires_at  TIMESTAMPTZ NOT NULL
used_at     TIMESTAMPTZ
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
```

**`organization_invitations`**
```
id              UUID        PK, default gen_random_uuid()
org_id          UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE
email           TEXT        NOT NULL
role            TEXT        NOT NULL CHECK (role IN ('admin','recruiter','reviewer'))
invited_by      UUID        NOT NULL REFERENCES users(id) ON DELETE SET NULL
token_hash      TEXT        NOT NULL, UNIQUE    -- SHA-256 of 32-byte random token
expires_at      TIMESTAMPTZ NOT NULL
accepted_at     TIMESTAMPTZ
revoked_at      TIMESTAMPTZ
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE (org_id, email) WHERE accepted_at IS NULL AND revoked_at IS NULL
```

**`audit_events`**
```
id          UUID        PK, default gen_random_uuid()
org_id      UUID        REFERENCES organizations(id) ON DELETE SET NULL
actor_id    UUID        REFERENCES users(id) ON DELETE SET NULL
target_id   UUID        (nullable — the affected entity ID)
event_type  TEXT        NOT NULL
payload     JSONB       NOT NULL DEFAULT '{}'
ip_hash     TEXT
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
```
No UPDATE, no DELETE. Rows are insert-only. `org_id` and `actor_id` use SET NULL on cascade so event history is preserved when an org or user is deleted.

### 4.2 Indexes

```sql
-- users
CREATE INDEX ix_users_email ON users(email);

-- memberships
CREATE INDEX ix_memberships_user_id ON memberships(user_id);
CREATE INDEX ix_memberships_org_id ON memberships(org_id);

-- auth_sessions
CREATE INDEX ix_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX ix_auth_sessions_family_id ON auth_sessions(family_id);
CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions(expires_at);

-- audit_events
CREATE INDEX ix_audit_events_org_id ON audit_events(org_id);
CREATE INDEX ix_audit_events_actor_id ON audit_events(actor_id);
CREATE INDEX ix_audit_events_created_at ON audit_events(created_at);
```

### 4.3 SQLAlchemy Model Files

```
services/api/app/models/
├── __init__.py         — imports all models for Alembic registration
├── user.py             — User, EmailVerificationToken, PasswordResetToken
├── organization.py     — Organization, Membership, OrganizationInvitation
├── session.py          — AuthSession
└── audit.py            — AuditEvent
```

All models inherit from `app.database.Base`. `updated_at` columns use `onupdate=datetime.utcnow`. All UUIDs use `server_default=text("gen_random_uuid()")`.

---

## 5. Authentication Architecture

### 5.1 Password Hashing

Library: `argon2-cffi`

Parameters (OWASP recommended minimum for interactive login):
```python
PasswordHasher(
    time_cost=2,        # iterations
    memory_cost=65536,  # 64 MiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
    encoding="utf-8",
)
```

Operations: `ph.hash(password)`, `ph.verify(hash, password)`, `ph.check_needs_rehash(hash)` (rehash on login if parameters changed).

### 5.2 JWT Access Tokens

Library: `pyjwt`

Algorithm: HS256  
Signing key: `settings.secret_key` (from `SECRET_KEY` env var, min 32 bytes enforced at startup)  
Lifetime: 10 minutes  

Claims:
```json
{
  "iss": "expertseat",
  "aud": "expertseat-api",
  "sub": "<user_id>",
  "sid": "<auth_session_id>",
  "org": "<org_id>",
  "mid": "<membership_id>",
  "role": "admin|recruiter|reviewer",
  "iat": 1234567890,
  "exp": 1234568490,
  "jti": "<uuid>"
}
```

The access token payload contains the verified workspace context (`org`, `mid`, `role`) so that workspace endpoint guards do not require a database round-trip on every request.

Validation: `jwt.decode(token, key, algorithms=["HS256"], audience="expertseat-api")`. Expired tokens raise `ExpiredSignatureError` → 401. Invalid tokens raise `InvalidTokenError` → 401.

### 5.3 Refresh Tokens

Generation: `secrets.token_bytes(32)` → hex-encode for cookie value (64 hex chars)  
Storage: `hashlib.sha256(token_bytes).hexdigest()` stored in `auth_sessions.refresh_token_hash`  
Lifetime: 14 days  
Cookie name: `es_refresh`  
Cookie attributes: `HttpOnly=True`, `Secure=True` (production), `SameSite=Lax`, `Path=/api/v1/auth`, `Max-Age=1209600`

Rotation protocol on `POST /api/v1/auth/refresh`:
1. Extract `es_refresh` cookie
2. Hash it → look up `auth_sessions` row
3. If not found or revoked → 401 INVALID_REFRESH_TOKEN
4. If found but `revoked_at IS NOT NULL` → **reuse detected**: revoke all sessions with same `family_id`, return 401 REFRESH_TOKEN_REUSED
5. If `expires_at < now()` → 401 REFRESH_TOKEN_EXPIRED
6. Generate new refresh token, hash it
7. Update session: `refresh_token_hash=new_hash`, `last_used_at=now()`, optionally extend `expires_at`
8. Issue new JWT access token
9. Set new `es_refresh` cookie, set new `es_csrf` cookie
10. Return `{"access_token": "...", "token_type": "bearer"}`

Note: the access token is also set in an HttpOnly cookie (`es_access`) for browser clients. The JSON body response is provided for programmatic clients.

### 5.4 Cookie Inventory

| Cookie | HttpOnly | Secure (prod) | SameSite | Path | Content |
|---|---|---|---|---|---|
| `es_access` | Yes | Yes | Lax | `/api/v1` | JWT access token |
| `es_refresh` | Yes | Yes | Lax | `/api/v1/auth` | Opaque refresh token (hex) |
| `es_csrf` | **No** | Yes | Lax | `/` | 32-byte random hex value |

The CSRF cookie is readable by JavaScript so the frontend can include it in the `X-CSRF-Token` request header. The backend validates that `X-CSRF-Token == es_csrf` on all state-mutating requests.

### 5.5 CSRF and Origin Protection

All state-mutating endpoints (POST, PUT, PATCH, DELETE) enforce:
1. **Origin header validation**: `request.headers.get("origin")` must be in `settings.cors_allowed_origins`. Requests without an Origin header from a browser context are rejected (405 for API clients, or accepted from trusted server contexts where Origin is absent).
2. **Double-submit CSRF**: `X-CSRF-Token` header must equal the `es_csrf` cookie value.

Implemented as a FastAPI dependency `require_csrf()` composed with `require_auth()`. The health endpoints and GET endpoints are exempt.

### 5.6 Settings Additions

New fields added to `app/config.py`:
```python
secret_key: str          # SECRET_KEY env var, min 32 chars enforced in validator
access_token_ttl: int = 600          # 10 minutes
refresh_token_ttl: int = 1209600     # 14 days
rate_limit_auth_max: int = 10        # max attempts per window
rate_limit_auth_window: int = 60     # window in seconds
mailpit_host: str = "localhost"
mailpit_port: int = 1025
email_from: str = "noreply@expertseat.local"
```

Production validation: `secret_key` must be set (no default). The model validator extends the existing production check to also validate `secret_key`.

---

## 6. Session Architecture

### 6.1 Session Lifecycle

```
Register → EmailVerification → Login → [access_token + refresh_token in cookies]
                                           ↓
                                    Access expires (10 min)
                                           ↓
                           Browser uses refresh cookie → POST /auth/refresh
                                           ↓
                              New access token + new refresh token
                                           ↓
                             Logout: revoke single session
                          Logout-all: revoke all user sessions
```

### 6.2 Session Storage

`auth_sessions` table (PostgreSQL). Each active session has exactly one row. On rotation, the row is updated in-place (refresh_token_hash changes, revoked_at stays NULL). On logout, `revoked_at = now()`. Expired sessions are logically dead but remain for audit purposes; a background cleanup task (not Milestone 1) will purge them.

### 6.3 Session Listing

`GET /api/v1/auth/sessions` returns all non-revoked, non-expired sessions for the current user. Response includes: `id`, `ip_address_hash` (truncated for display), `user_agent`, `last_used_at`, `created_at`, `current: bool` (matches the current `sid` JWT claim).

### 6.4 Session Revocation

`DELETE /api/v1/auth/sessions/{session_id}` — revoke a specific session (user can only revoke their own).  
`POST /api/v1/auth/logout` — revoke the current session.  
`POST /api/v1/auth/logout-all` — revoke all sessions (sets `revoked_at` on all non-revoked sessions for the user).

---

## 7. Tenant-Isolation Model

### 7.1 Active Organization Context

The active organization is determined **exclusively** from the JWT access token claims (`org`, `mid`, `role`). No client-supplied organization identifier is trusted.

A workspace dependency `get_workspace_context()` extracts `org_id`, `membership_id`, and `role` from the validated JWT. All workspace-scoped endpoints use this dependency. No endpoint accepts an `org_id` path or query parameter as the authority for which organization to operate on.

### 7.2 Workspace Switching

When a user switches organizations (i.e., selects a different workspace), they call `POST /api/v1/auth/switch-org` with `{"org_id": "..."}` in the body. The server:
1. Validates the user has an active membership in the requested org
2. Issues a new JWT access token with the new org context
3. Updates the `auth_sessions` row: `org_id=new_org_id`, `membership_id=new_membership_id`
4. Sets new `es_access` and `es_csrf` cookies (refresh token is unchanged)

### 7.3 Cross-Tenant Data Access Prevention

Every database query in workspace-scoped endpoints is filtered by `org_id` from the JWT. The service layer never accepts a raw org_id from the request body or path parameter as the authorization context. The dependency chain ensures this: `require_role("admin")` calls `get_workspace_context()` which calls `get_current_user()` which validates the JWT.

---

## 8. RBAC Matrix

| Permission | admin | recruiter | reviewer |
|---|---|---|---|
| View member list | ✓ | ✓ | ✓ |
| Invite members | ✓ | — | — |
| Change member role | ✓ | — | — |
| Disable/reactivate members | ✓ | — | — |
| Revoke invitations | ✓ | — | — |
| View organization settings | ✓ | ✓ | ✓ |
| Update organization settings | ✓ | — | — |
| View audit log | ✓ | — | — |
| Create blueprints (Milestone 2) | ✓ | ✓ | — |
| Review candidates (Milestone 2) | ✓ | ✓ | ✓ |

### 8.1 Last-Admin Protection

Before executing any of: role demotion from admin, member disable, member removal — the service checks transactionally whether this user is the last active admin in the organization. If yes, the operation is rejected with `LAST_ADMIN_PROTECTED` (409 Conflict).

Implementation: `SELECT COUNT(*) FROM memberships WHERE org_id=$1 AND role='admin' AND is_active=TRUE FOR UPDATE`. If count == 1 and the target is that admin, raise `LastAdminError`.

### 8.2 Centralized Policy Functions

All role checks use module `app/auth/policy.py`:
```python
def require_role(minimum_role: str):
    """FastAPI dependency. Raises 403 if JWT role does not meet minimum."""

def check_can_manage_member(actor_role: str, target_role: str) -> None:
    """Admins can manage anyone. Others cannot manage anyone. Raises PermissionError."""
```

No role check logic is duplicated across route handlers.

---

## 9. Email-Delivery Strategy

### 9.1 Provider Interface

```python
# app/email/base.py
class EmailProvider(Protocol):
    async def send(self, to: str, subject: str, html_body: str, text_body: str) -> None: ...
```

### 9.2 SMTP Implementation

Uses Python stdlib `smtplib` (no new dependency) via `asyncio.to_thread()` so it does not block the event loop. Connection is opened fresh per email (no persistent connection state in Milestone 1).

```python
# app/email/smtp.py
class SmtpEmailProvider:
    def __init__(self, host: str, port: int, from_address: str): ...
    async def send(self, to: str, subject: str, html_body: str, text_body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, html_body, text_body)
```

### 9.3 Fake Implementation (Tests)

```python
# app/email/fake.py
class FakeEmailProvider:
    sent: list[dict]

    async def send(self, to: str, subject: str, html_body: str, text_body: str) -> None:
        self.sent.append({"to": to, "subject": subject})
```

The `FakeEmailProvider` is injected via FastAPI dependency override in integration tests.

### 9.4 Dependency Injection

```python
# app/email/deps.py
def get_email_provider() -> EmailProvider:
    return SmtpEmailProvider(
        host=settings.mailpit_host,
        port=settings.mailpit_port,
        from_address=settings.email_from,
    )
```

Route handlers receive the provider via `provider: EmailProvider = Depends(get_email_provider)`. Tests override `get_email_provider` with the fake.

### 9.5 Mailpit (Dev Email Server)

Added to `infrastructure/docker-compose.yml`:
- SMTP: port 1025 (bound to 127.0.0.1)
- Web UI: port 8025 (bound to 127.0.0.1)
- Image: `axllent/mailpit:latest` (pinned to a digest in the compose file)

`.env.example` updated with:
```
MAILPIT_HOST=localhost
MAILPIT_PORT=1025
EMAIL_FROM=noreply@expertseat.local
```

---

## 10. API Surface

All endpoints under prefix `/api/v1`.

### 10.1 Auth Endpoints (`/auth`)

| Method | Path | Auth | Rate limit | Description |
|---|---|---|---|---|
| POST | `/auth/register` | None | 10/60s per IP | Register new user |
| POST | `/auth/verify-email` | None | 10/60s per IP | Verify email with 6-digit code |
| POST | `/auth/resend-verification` | None | 3/60s per IP | Resend verification email |
| POST | `/auth/login` | None | 10/60s per IP | Login, get cookies |
| POST | `/auth/refresh` | Refresh cookie | 30/60s per IP | Rotate refresh token |
| POST | `/auth/logout` | Access cookie | None | Revoke current session |
| POST | `/auth/logout-all` | Access cookie | None | Revoke all sessions |
| POST | `/auth/forgot-password` | None | 3/60s per IP | Send password reset email |
| POST | `/auth/reset-password` | None | 10/60s per IP | Reset password with token |
| POST | `/auth/change-password` | Access cookie + CSRF | None | Change password (authenticated) |
| POST | `/auth/switch-org` | Access cookie + CSRF | None | Switch active organization |
| GET | `/auth/sessions` | Access cookie | None | List active sessions |
| DELETE | `/auth/sessions/{id}` | Access cookie + CSRF | None | Revoke a session |
| GET | `/auth/me` | Access cookie | None | Current user info |

### 10.2 Workspace Endpoints (`/workspace`)

| Method | Path | Role required | Description |
|---|---|---|---|
| POST | `/workspace/organizations` | None (authenticated) | Create organization (caller becomes admin) |
| GET | `/workspace/organizations` | Any member | List user's organizations |
| GET | `/workspace/organizations/{org_id}` | Any member | Organization details |
| GET | `/workspace/members` | Any member | List members in active org |
| GET | `/workspace/members/{user_id}` | Any member | Member detail |
| PATCH | `/workspace/members/{user_id}` | admin | Update member role |
| DELETE | `/workspace/members/{user_id}` | admin | Remove member (last-admin protection) |
| PATCH | `/workspace/members/{user_id}/status` | admin | Enable/disable member |
| GET | `/workspace/invitations` | admin | List pending invitations |
| POST | `/workspace/invitations` | admin | Send invitation |
| DELETE | `/workspace/invitations/{id}` | admin | Revoke invitation |
| POST | `/workspace/invitations/accept` | None | Accept invitation (token in body) |
| GET | `/workspace/settings` | Any member | Get org settings |
| PATCH | `/workspace/settings` | admin | Update org settings |
| GET | `/workspace/audit` | admin | Paginated audit log |

### 10.3 Error Response Format

All API errors use:
```json
{
  "error": "SNAKE_CASE_CODE",
  "message": "Human-readable description"
}
```

HTTP status codes:
- 400: validation errors, invalid input
- 401: unauthenticated (INVALID_TOKEN, EXPIRED_TOKEN, MISSING_TOKEN)
- 403: insufficient role (INSUFFICIENT_ROLE, CSRF_VALIDATION_FAILED)
- 404: resource not found
- 409: conflict (LAST_ADMIN_PROTECTED, EMAIL_ALREADY_EXISTS, SLUG_ALREADY_EXISTS)
- 422: unprocessable (Pydantic validation)
- 429: rate limited (RATE_LIMITED)
- 500: internal server error (no details exposed)

### 10.4 Rate Limiting

Redis fixed-window counter per endpoint group:
```
key: "rate:{endpoint_group}:{sha256(ip)[:16]}"
INCR key
if new_count == 1: EXPIRE key {window_seconds}
if new_count > {max}: return 429
```

IP is one-way hashed (SHA-256, first 16 hex chars) before storage. Fail-closed: if Redis is unreachable on an auth endpoint, the request is rejected with 503.

---

## 11. Frontend Routes

### 11.1 Public Routes (no auth required)

| Path | Page | Description |
|---|---|---|
| `/` | Home | Landing page (updated) |
| `/sign-up` | RegisterPage | Registration form |
| `/verify-email` | VerifyEmailPage | 6-digit code entry |
| `/sign-in` | SignInPage | Login form |
| `/forgot-password` | ForgotPasswordPage | Request reset email |
| `/reset-password` | ResetPasswordPage | Enter new password (token in URL) |
| `/invite/[token]` | AcceptInvitationPage | Accept org invitation |
| `/auth-error` | AuthErrorPage | Token invalid / link expired / access denied |

### 11.2 Protected Routes (require valid JWT cookie)

| Path | Page | Role required | Description |
|---|---|---|---|
| `/dashboard` | DashboardPage | Any | Post-login landing, org picker if no org |
| `/workspace/members` | MembersPage | Any | Member list |
| `/workspace/members/invite` | InviteMemberPage | admin | Invite form |
| `/workspace/invitations` | InvitationsPage | admin | Pending invitations |
| `/workspace/settings` | WorkspaceSettingsPage | admin | Org name / slug |
| `/account/profile` | ProfilePage | Any | Name, email, password change |
| `/account/sessions` | SessionsPage | Any | Active sessions list |
| `/workspace/audit` | AuditLogPage | admin | Audit event table |

### 11.3 Auth Middleware

`middleware.ts` at the root of `apps/web/src/`:
- Reads the `es_access` cookie (httpOnly — available server-side in Next.js middleware)
- For protected routes: if cookie absent or JWT expired, redirect to `/sign-in?next=<path>`
- For `/sign-in` and `/sign-up`: if valid cookie present, redirect to `/dashboard`
- Passes role from JWT to headers so layout components can gate admin-only nav items

---

## 12. Threat Model

### 12.1 Assets

- User credentials (passwords, email addresses)
- JWT access tokens (10-minute authorization grants)
- Refresh tokens (14-day session continuity)
- Organization data (member lists, settings)
- Audit logs

### 12.2 Threats and Mitigations

| Threat | Mitigation |
|---|---|
| Password brute-force | Argon2id (computationally expensive), rate limiting (10/60s per IP), account lockout on excessive failures logged to audit |
| Credential stuffing | Rate limiting per IP + per-email, Argon2id slows offline cracking if DB leaked |
| JWT forgery | HS256 with 256-bit SECRET_KEY (validated at startup); jti not currently checked (replay window = token lifetime = 10 min) |
| Refresh token theft | HttpOnly cookie prevents JS access; SameSite=Lax prevents CSRF on refresh; token rotation invalidates stolen tokens within one rotation cycle |
| Refresh token replay | Family revocation: if a rotated token is presented, the entire family is revoked immediately |
| CSRF | Double-submit cookie pattern: X-CSRF-Token must match es_csrf; Origin header validation |
| Session fixation | New session ID on every login; no session created before authentication |
| Tenant data leakage | org_id sourced exclusively from JWT; all DB queries filter by JWT org_id |
| Invitation abuse | Tokens expire in 7 days; token is single-use; accepting is rate-limited |
| Email enumeration | Registration, forgot-password, and resend-verification responses are identical whether the email exists or not; timing side-channels mitigated via constant-time comparison |
| Secret in logs | No exception messages or user data logged; exc_type only (inherited from Milestone 0) |
| SQL injection | SQLAlchemy ORM with parameterized queries throughout |
| Mass assignment | Pydantic schemas with explicit field declarations; no `**kwargs` from request into DB |
| Password reset token theft | Single-use, 1-hour TTL, SHA-256 hashed before storage |
| Information disclosure | Generic 500 handler returns `{"error": "Internal server error"}` only |

### 12.3 Out of Scope for this Milestone

- Timing attacks on Argon2 verification (mitigated by computational cost making timing differences negligible)
- Side-channel attacks on constant-time comparisons (Python `hmac.compare_digest` used for token comparisons)
- Physical access / server-side attacks

---

## 13. Migration Plan

### 13.1 Migration 0002

File: `services/api/alembic/versions/0002_auth_workspace.py`

`upgrade()`:
1. Enable `pgcrypto` extension for `gen_random_uuid()`
2. Create `users` table
3. Create `organizations` table
4. Create `memberships` table with FK constraints
5. Create `auth_sessions` table with FK constraints
6. Create `email_verification_tokens` table
7. Create `password_reset_tokens` table
8. Create `organization_invitations` table
9. Create `audit_events` table
10. Create all indexes listed in section 4.2

`downgrade()`:
1. Drop all indexes
2. Drop tables in reverse dependency order: audit_events, organization_invitations, password_reset_tokens, email_verification_tokens, auth_sessions, memberships, organizations, users
3. Drop `pgcrypto` extension (only if it was not pre-existing — check pg_extension first)

The migration is fully reversible. `make migrate-full` (upgrade → downgrade → re-upgrade) must pass.

---

## 14. Testing Plan

### 14.1 Backend Integration Tests (real PostgreSQL + Redis)

Located in `services/api/tests/integration/`. Marked `@pytest.mark.integration`. Require `DATABASE_URL` and `REDIS_URL` environment variables.

**conftest additions:**
- `db_session` fixture: transaction-wrapped session, rolls back after each test
- `redis_client` fixture: real Redis connection, flushes test keys after each test
- `fake_email` fixture: `FakeEmailProvider` injected via dependency override
- `auth_client` fixture: TestClient with registered + verified + logged-in user

**Test files:**

`test_registration.py`:
- Successful registration creates user, sends verification email
- Duplicate email returns 409
- Invalid email format returns 422
- Password too short returns 422
- Rate limiting: 11th request returns 429

`test_email_verification.py`:
- Valid code verifies user, marks email_verified=True
- Expired code returns 401
- Already-used code returns 401
- Invalid code returns 401

`test_login.py`:
- Valid credentials set es_access + es_refresh + es_csrf cookies
- Invalid password returns 401
- Unverified email returns 401
- Rate limiting: 11th failed attempt returns 429

`test_refresh.py`:
- Refresh rotates token and issues new access token
- Expired refresh token returns 401
- Revoked refresh token returns 401
- **Replay detection**: using an old (already-rotated) refresh token revokes entire family + returns 401
- Missing refresh cookie returns 401

`test_logout.py`:
- Logout revokes session; subsequent refresh returns 401
- Logout-all revokes all sessions for user

`test_password_reset.py`:
- Valid reset flow: forgot → email sent → reset with token → old password rejected, new password accepted
- Expired token returns 401
- Used token returns 401

`test_change_password.py`:
- Authenticated change: correct current password → success
- Wrong current password → 401
- New password same as old → 400

`test_sessions.py`:
- Session list returns current session with `current: true`
- Revoking another session invalidates its refresh token
- Cannot revoke another user's session (404)

`test_workspace.py`:
- Create org: caller becomes admin, membership created, audit event created
- Create second org: user has two memberships
- List orgs: returns only user's orgs
- Switch org: new JWT claims reflect new org

`test_members.py`:
- List members: all roles can view
- Update role: admin only; non-admin returns 403
- Disable member: admin only; last-admin protection returns 409
- Remove member: last-admin protection returns 409

`test_invitations.py`:
- Admin sends invitation: email sent, invitation row created
- Non-admin invitation attempt returns 403
- Accept invitation: user registered, membership created
- Expired invitation returns 401
- Already-accepted invitation returns 409

`test_tenant_isolation.py`:
- User A in Org A cannot access Org B members endpoint (403)
- User A cannot revoke User B's session even with valid JWT
- After switch-org, old org context is no longer accessible

`test_audit.py`:
- Audit events are created for: registration, login, logout, password-change, member-invite, role-change, org-settings-change
- Non-admin cannot access /workspace/audit (403)
- Audit log is append-only: no update/delete endpoint exists

### 14.2 Frontend Component Tests

Located in `apps/web/src/**/__tests__/`.

`RegisterForm.test.tsx`:
- Renders all fields
- Submits with valid data
- Shows error on password mismatch
- Shows error on short password
- Shows server error message on 409

`SignInForm.test.tsx`:
- Renders email/password fields
- Shows error on 401

`VerifyEmailForm.test.tsx`:
- Accepts 6-digit code
- Shows error on invalid code

`ForgotPasswordForm.test.tsx`:
- Submits email
- Shows success state (same message whether email exists or not)

`ResetPasswordForm.test.tsx`:
- Validates password match
- Calls API with token from URL

`MembersTable.test.tsx`:
- Renders member list
- Shows role badges
- Admin sees action buttons; non-admin does not

`InviteForm.test.tsx`:
- Validates email field
- Selects role

`WorkspaceSettings.test.tsx`:
- Renders name and slug
- Shows validation error for short name

### 14.3 E2E Tests (Playwright)

Located in `apps/web/e2e/`.

**Flow 1: Full registration and login**
1. Navigate to /sign-up
2. Fill form, submit
3. Receive code via Mailpit API
4. Enter code at /verify-email
5. Redirected to /dashboard
6. Page shows "Create your first workspace"
7. Sign out → redirected to /sign-in

**Flow 2: Organization creation and invitation**
1. Register and verify (reuse helper)
2. Create organization at /dashboard
3. Navigate to /workspace/members/invite
4. Invite a second email address
5. Check Mailpit for invitation email
6. Open invitation link in new browser context
7. Register and accept invitation
8. Verify second user is listed as member in Org A

**Flow 3: RBAC enforcement**
1. Sign in as recruiter (invited with recruiter role)
2. Navigate to /workspace/settings → redirected to /auth-error
3. Navigate to /workspace/invitations → redirected to /auth-error
4. Verify /workspace/members is accessible and shows member list

**Flow 4: Session management**
1. Sign in in two browser contexts (two sessions)
2. Navigate to /account/sessions in context A → two sessions listed
3. Revoke context B's session
4. In context B, attempt to refresh → redirected to /sign-in
5. Sign out context A

**Flow 5: Tenant isolation**
1. User A creates Org A
2. User B creates Org B
3. User A attempts to fetch /api/v1/workspace/members while claiming Org B (via modified cookie or direct API call)
4. Verify 401/403 is returned — Org B data not accessible

### 14.4 Coverage Expectations

- Auth endpoints: 100% behavioral coverage via integration tests
- Workspace endpoints: 100% behavioral coverage via integration tests
- Security paths (refresh rotation, replay, tenant isolation): explicit test cases, not just happy-path
- Frontend form components: all submit, error, and loading states covered
- E2E: 5 flows as above

---

## 15. CI Changes

### 15.1 New Scripts

**`scripts/check_auth_integration.sh`**
```bash
#!/usr/bin/env bash
# Run backend integration tests against real PostgreSQL + Redis.
# Called by: check_all.sh (after check_infrastructure.sh) and the CI auth-integration job.
set -euo pipefail
cd "$(dirname "$0")/../services/api"
uv sync --locked --extra dev
uv run pytest tests/integration/ -v --tb=short
```

**`scripts/check_e2e.sh`**
```bash
#!/usr/bin/env bash
# Run Playwright E2E tests against running frontend + API.
# Prerequisites: API server on :8000, frontend on :3000, Mailpit on :8025.
set -euo pipefail
cd "$(dirname "$0")/../apps/web"
pnpm exec playwright install --with-deps chromium
pnpm exec playwright test
```

### 15.2 New CI Job

```yaml
milestone-1-e2e:
  name: "Milestone 1 end-to-end"
  runs-on: ubuntu-latest
  needs: [frontend, backend, migrations]
  env:
    DATABASE_URL: postgresql://expertseat:expertseat_dev@localhost:5432/expertseat
    REDIS_URL: redis://localhost:6379/0
    APP_ENV: test
    SECRET_KEY: <64-char hex generated for CI via GitHub Actions secret>
    NEXT_PUBLIC_API_BASE_URL: http://localhost:8000
  steps:
    - Checkout
    - Setup Node.js 24 + pnpm 11.12.0
    - Setup Python 3.12 + uv 0.11.7
    - Start infrastructure (Docker Compose: postgres, redis, mailpit)
    - Wait for healthy
    - Run migrations (scripts/check_migrations.sh)
    - Start Uvicorn (background)
    - Start Next.js dev server (background)
    - Wait for API :8000 and frontend :3000
    - Run auth integration tests (scripts/check_auth_integration.sh)
    - Run E2E tests (scripts/check_e2e.sh)
    - Stop infrastructure
```

### 15.3 `check_all.sh` Update

Add step group after `check_infrastructure.sh`:
- Run `check_auth_integration.sh` (requires services to be up)
- Run `check_e2e.sh` (requires dev servers)

The check_all.sh phase labels become:
1. Versions (1–6)
2. Static analysis (7–17)
3. Infrastructure + migrations (18–23)
4. Auth integration (new)
5. Runtime smoke (existing 24–47)
6. E2E (new)
7. Security (48–50)
8. Cleanup (51–54)

### 15.4 Branch Protection

Add `Milestone 1 end-to-end` as a required status check on `main` (8th required check).

---

## 16. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Sync SQLAlchemy blocking under load | Low (dev/test context) | Low | Acceptable for Milestone 1; async migration planned when load warrants |
| PyJWT HMAC key exposure in logs | Medium | High | `secret_key` validated at startup; never logged; generic exception handler logs `exc_type` only |
| Argon2id parameters too slow for test suite | Low | Medium | Tests use a low-cost PasswordHasher override (`time_cost=1, memory_cost=8`) for speed; prod parameters only in production |
| Cookie SameSite=Lax allows some CSRF on navigation | Low | Low | Origin header validation provides secondary defense; Strict would break OAuth redirect flows needed in Milestone 6 |
| Redis unavailability blocks auth completely (fail-closed) | Low | High | Redis is a hard dependency for auth in this design; acceptable trade-off for security; readiness check reflects Redis health |
| Mailpit not available in CI | Low | Medium | Auth integration tests use FakeEmailProvider; E2E tests use Mailpit in Docker Compose (same as runtime job) |
| Next.js middleware JWT parsing adds latency | Low | Low | Middleware only reads cookie presence + JWT expiry; no DB call; overhead is negligible |
| Playwright flakiness in CI | Medium | Medium | Use `--retries=2` in CI; isolate each E2E test with fresh DB state via test hooks |

---

## 17. Proposed Commit Sequence

1. `docs: define milestone 1 architecture and threat model` — MILESTONE_1_PLAN.md + 6 ADRs
2. `feat(api): add auth dependencies to pyproject.toml` — argon2-cffi, pyjwt; update uv.lock
3. `feat(infra): add mailpit to docker-compose and update env example` — docker-compose.yml, .env.example
4. `feat(api): add auth config fields` — secret_key, token TTLs, rate limit params, email config; update tests
5. `feat(api): define sqlalchemy models for auth and workspace` — 4 model files + updated models/__init__.py
6. `feat(api): add alembic migration 0002 for auth and workspace tables` — 0002_auth_workspace.py; verify migrate-full passes
7. `feat(api): implement password hashing and token utilities` — app/auth/crypto.py, app/auth/tokens.py, app/auth/cookies.py
8. `feat(api): implement redis rate limiting` — app/auth/ratelimit.py
9. `feat(api): implement email provider interface and smtp + fake implementations` — app/email/
10. `feat(api): implement auth service` — app/services/auth.py (register, verify, login, refresh, logout, password-reset, sessions)
11. `feat(api): implement auth router` — app/routers/auth.py (14 endpoints)
12. `feat(api): implement workspace service` — app/services/workspace.py (members, invitations, settings, audit)
13. `feat(api): implement workspace router` — app/routers/workspace.py (15 endpoints)
14. `feat(api): add csrf and origin middleware` — app/auth/csrf.py, wire into main.py
15. `feat(api): add auth integration tests` — services/api/tests/integration/ (all test files)
16. `feat(web): add middleware and auth pages` — middleware.ts, public route pages
17. `feat(web): add protected workspace pages` — dashboard, members, settings, profile, sessions, audit
18. `feat(web): add frontend component tests` — __tests__/ files
19. `feat(web): add playwright and e2e tests` — package.json update, playwright.config.ts, e2e/ flows
20. `feat(ci): add auth integration and e2e scripts and ci job` — check_auth_integration.sh, check_e2e.sh, check_all.sh update, ci.yml new job
21. `docs: update readme architecture testing and roadmap for milestone 1` — all doc updates
22. `docs: milestone 1 clean-clone verification` — docs/verification/MILESTONE_1_CLEAN_CLONE.md

---

## Internal Consistency Checks

- [ ] Migration 0002 creates exactly the 8 tables in section 4.1 — no more, no less
- [ ] All 14 auth endpoints in section 10.1 have corresponding route handlers
- [ ] All 15 workspace endpoints in section 10.2 have corresponding route handlers
- [ ] Cookie names (`es_access`, `es_refresh`, `es_csrf`) are consistent across sections 5.4, 5.5, 6.1, 11.3
- [ ] `family_id` reuse-detection logic in section 5.3 matches the `auth_sessions` schema in section 4.1
- [ ] `last-admin protection` in section 8.1 is tested in `test_members.py` in section 14.1
- [ ] `switch-org` endpoint appears in both section 10.1 and section 7.2
- [ ] All 5 E2E flows in section 14.3 correspond to real routes in section 11
- [ ] CI job `milestone-1-e2e` calls both `check_auth_integration.sh` and `check_e2e.sh` (section 15.2)
- [ ] SECRET_KEY env var is validated in settings (section 5.6) and required in CI job (section 15.2)
- [ ] Argon2id test-speed override is mentioned in Risks (section 16) and referenced in test plan (section 14.1)
- [ ] Commit sequence (section 17) starts with docs and ends with verification — no implementation before plan
