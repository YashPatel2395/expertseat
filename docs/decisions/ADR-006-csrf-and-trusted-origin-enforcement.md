# ADR-006: CSRF and Trusted-Origin Enforcement

**Status**: Accepted  
**Date**: 2026-07-13  
**Milestone**: 1

---

## Context

Because ExpertSeat uses HttpOnly cookies for authentication, the browser sends cookies automatically on cross-site requests. This makes CSRF attacks theoretically possible: a malicious website can trigger a state-mutating request to the ExpertSeat API using the victim's cookies.

SameSite=Lax (the chosen cookie attribute) prevents cross-site POST requests in most modern browsers, but:
- Not all browsers implement SameSite consistently
- GET-based state changes would still be vulnerable (we avoid GET-based state changes, but defense-in-depth is warranted)
- The SameSite attribute is set by the server and could be misconfigured

A secondary CSRF defense is required.

---

## Decision

Use the **double-submit cookie pattern** combined with **Origin header validation**. Both checks are required on all state-mutating requests (POST, PUT, PATCH, DELETE).

### Double-submit cookie pattern

At login (and on every token refresh), the server:
1. Generates 32 random bytes via `secrets.token_bytes(32)`
2. Hex-encodes to a 64-character string
3. Sets cookie `es_csrf` with attributes: `HttpOnly=False`, `Secure=True` (prod), `SameSite=Lax`, `Path=/`, `Max-Age=<same as access token>`

The frontend JavaScript reads `es_csrf` and includes its value in the `X-CSRF-Token` header on every state-mutating request.

The server middleware validates: `X-CSRF-Token header == es_csrf cookie`. On mismatch: 403 CSRF_VALIDATION_FAILED.

**Why this works**: A cross-site attacker cannot read the `es_csrf` cookie (SameSite=Lax prevents the request from being initiated cross-site on navigation, and even if somehow sent, the attacker's page running at a different origin cannot read the cookie value via JavaScript due to the same-origin policy). Therefore, the attacker cannot set the correct `X-CSRF-Token` header.

### Origin header validation

On all state-mutating requests, the middleware checks:
```python
origin = request.headers.get("origin")
if origin and origin not in settings.cors_allowed_origins:
    raise HTTPException(403, "ORIGIN_NOT_ALLOWED")
```

Requests without an `Origin` header (e.g., server-to-server calls, curl without the header) are allowed through, because the absence of Origin typically indicates a non-browser context. Browser state-mutating requests always include Origin.

### Implementation

A FastAPI dependency `require_csrf`:
```python
async def require_csrf(
    request: Request,
    csrf_header: str | None = Header(None, alias="X-CSRF-Token"),
):
    csrf_cookie = request.cookies.get("es_csrf")
    if not csrf_cookie or not csrf_header:
        raise HTTPException(403, detail={"error": "CSRF_VALIDATION_FAILED"})
    if not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(403, detail={"error": "CSRF_VALIDATION_FAILED"})
```

`hmac.compare_digest` is used to prevent timing attacks on the comparison.

All state-mutating route handlers include `_: None = Depends(require_csrf)`.

### Exemptions

- `GET`, `HEAD`, `OPTIONS` endpoints: exempt (read-only, no state mutation)
- `POST /api/v1/auth/login`: exempt (user is not yet authenticated; CSRF only applies to authenticated sessions)
- `POST /api/v1/auth/register`: exempt
- `POST /api/v1/auth/verify-email`: exempt (token in body is the credential; endpoint is idempotent and enumeration-resistant)
- `POST /api/v1/auth/forgot-password`: exempt (unauthenticated; no state visible to the caller)
- `POST /api/v1/auth/resend-verification`: exempt (unauthenticated)

All other state-mutating endpoints — including `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`, `POST /api/v1/auth/logout-all`, `POST /api/v1/auth/switch-org`, and `POST /api/v1/workspace/invitations/accept` — require `X-CSRF-Token`.

---

## Consequences

- All authenticated state-mutating frontend requests must send the `X-CSRF-Token` header
- Frontend must read the `es_csrf` cookie on page load and include it in fetch/axios configuration
- Adding new authenticated POST/PUT/PATCH/DELETE endpoints requires including `Depends(require_csrf)` — this is enforced by the code review checklist in CONTRIBUTING.md
- CSRF cookie is rotated on every token refresh (tied to access token lifetime, 10 minutes)

---

## Rejected Alternatives

**Synchronizer token pattern (server-side token store)**: More robust but requires a server-side lookup per request (Redis or DB). The double-submit pattern achieves the same goal without server state. Rejected for simplicity.

**Relying solely on SameSite=Lax**: Insufficient defense-in-depth. SameSite is a hint to the browser, not a protocol guarantee. Some browsers have bugs; some user agents are not browsers.

**Custom `X-Requested-With` header check**: A weaker version of Origin validation. Rejected in favor of explicit Origin checking which is more reliable.
