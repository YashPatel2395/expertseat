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

Use **Option C — Org context embedded in JWT access token claims**.

The JWT access token payload includes:
```json
{
  "org":  "<org_id>",
  "mid":  "<membership_id>",
  "role": "admin|recruiter|reviewer"
}
```

These values are set at login time (user selects or is assigned the default org) and updated on `POST /api/v1/auth/switch-org`. After a switch, a new JWT is issued. The refresh token session row is also updated to track the current org.

### Authorization dependency chain

```
Route handler
  └── require_role("admin")              ← raises 403 if role insufficient
        └── get_workspace_context()      ← extracts org_id, mid, role from JWT
              └── get_current_user()     ← validates JWT signature and expiry
                    └── oauth2_scheme()  ← reads es_access cookie
```

All workspace-scoped DB queries in the service layer receive `org_id` from `get_workspace_context()`. They never read org_id from request body, path parameters, or query strings as the *authorization context*.

### Why not Option A

Option A requires a DB round-trip on every request to validate membership. It also trusts the client to send the correct org ID, which means the server must always validate it. Embedding in the JWT achieves the same result with no DB round-trip: the JWT signature guarantees the claims were set by the server.

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

- No DB round-trip for authorization on workspace endpoints (only the JWT validation, which is pure computation)
- Role changes take effect at the next token refresh (up to 10 minutes delay)
- If an admin is demoted, they retain their old role in their current JWT for up to 10 minutes
- Acceptable trade-off: 10-minute window is short; for immediate revocation, the demoting admin can also invalidate the demoted user's sessions

---

## Rejected Alternatives

**Option A (org in request)**: Rejected. DB round-trip per request; still requires membership validation; no clear advantage over JWT-embedded approach.

**Option B (server-side session)**: Rejected. Requires Redis lookup per request (latency); complicates the auth architecture. The existing refresh token already handles session state; duplicating it in Redis is redundant.

**Separate introspection endpoint**: Rejected. Would require microservice-style token validation and is premature for Milestone 1.
