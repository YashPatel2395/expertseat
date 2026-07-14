# ADR-003: Tenant Context and Membership Authorization

**Status**: Accepted  
**Date**: 2026-07-13  
**Milestone**: 1

---

## Context

ExpertSeat is multi-tenant: a user can belong to multiple organizations (workspaces), each with a different role. Every workspace API call must operate in exactly one org context. The question is: where does the active org come from, and how is membership authorization verified?

Three options:

**Option A — Org ID in request (header, query param, or body)**  
The client sends `X-Org-ID: <uuid>` on every request. The server validates the user has a membership in that org.

**Option B — Org ID in session (server-side lookup per request)**  
The server stores the active org in the session/cache. Every request triggers a DB lookup to get the current org.

**Option C — Org ID in JWT access token (self-contained)**  
The JWT contains `org`, `mid` (membership_id), and `role` claims. Workspace endpoints extract context from the token with no DB round-trip.

---

## Decision

Use **Option C — Org context embedded in JWT access token claims**, with **DB-backed authorization** on every request to ensure revoked sessions, disabled users, and changed memberships take effect immediately.

The JWT access token payload includes:
```json
{
  "sub": "<user_id>",
  "sid": "<session_id>",
  "org": "<org_id>",
  "mid": "<membership_id>",
  "role": "admin|recruiter|reviewer"
}
```

These values are set at login time (user selects or is assigned the default org) and updated on `POST /api/v1/auth/switch-org`. After a switch, a new JWT is issued. The refresh token session row is also updated to track the current org.

### Authorization dependency chain

```
Route handler
  └── require_role("admin")              ← raises 403 if role insufficient
        └── get_workspace_context()      ← extracts org_id, mid, role from CurrentUser
              └── get_current_user()     ← validates JWT + performs full DB authorization
                    └── es_access cookie ← decoded and validated first
```

`get_current_user()` performs the following DB lookups on every authenticated request:
1. Decode and verify JWT signature + expiry
2. Load `AuthSession` by `session_id` → verify `revoked_at IS NULL`, `expires_at > now()`, `user_id` matches
3. Load `User` → verify `is_active = True`, `email_verified = True`
4. If `org_id` present: load `Membership` → verify `is_active = True`, `user_id` and `org_id` match
5. Load `Organization` → verify `is_active = True`
6. Derive `role` from DB `Membership.role` — never from the JWT `role` claim

The JWT `org`, `mid`, and `role` claims serve as **routing identifiers** to perform the DB lookups efficiently. The DB is the **authority**; the JWT merely identifies which rows to load.

All workspace-scoped DB queries in the service layer receive `org_id` from the DB-validated `CurrentUser`. They never read org_id from request body, path parameters, or query strings as the *authorization context*.

### Why not Option A

Option A requires the client to send the correct org ID, which the server must always validate anyway. Embedding in the JWT provides the same routing information without trusting the client, and the subsequent DB lookup provides the same validation. Embedding in the JWT is strictly better: we can validate identity (JWT sig) and authority (DB lookup) with a single known key.

### Workspace switching

`POST /api/v1/auth/switch-org` body: `{"org_id": "<uuid>"}`. The server:
1. Validates the user has an active membership in the requested org (DB lookup)
2. Loads the membership record
3. Issues a new access JWT with the new org/mid/role claims
4. Updates `auth_sessions.org_id` and `auth_sessions.membership_id`
5. Rotates the CSRF cookie
6. Does NOT rotate the refresh token (session continuity preserved)

---

## Consequences

- One DB round-trip per authenticated request (session + user + optional membership + optional org): typically 2–4 simple PK lookups, each indexed
- Role changes, membership deactivations, and session revocations take effect on the **next request** (no JWT expiry delay)
- Revoked sessions are immediately rejected even if the JWT has not yet expired
- Disabled users are immediately rejected
- Demoted admins lose their role on the next request after the membership row is updated

---

## Rejected Alternatives

**Option A (org in request)**: Rejected. DB round-trip per request; still requires membership validation; no clear advantage over JWT-embedded approach.

**Option B (server-side session)**: Rejected. Requires Redis lookup per request (latency); complicates the auth architecture. The existing refresh token already handles session state; duplicating it in Redis is redundant.

**Separate introspection endpoint**: Rejected. Would require microservice-style token validation and is premature for Milestone 1.
