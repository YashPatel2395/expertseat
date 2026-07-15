# ADR-001: Authentication Cookie Strategy

**Status**: Accepted  
**Date**: 2026-07-13  
**Milestone**: 1

---

## Context

ExpertSeat is a browser-based SaaS used by recruiters and interview reviewers. Authentication tokens must be delivered to the browser in a way that:

1. Prevents token theft via JavaScript (XSS)
2. Prevents CSRF attacks
3. Works with Next.js App Router server components and middleware
4. Supports token rotation without user interaction
5. Does not require localStorage or sessionStorage (poor security baseline)

The two primary options are:

**Option A — Bearer token in localStorage + Authorization header**  
Token is stored by JavaScript, sent as `Authorization: Bearer <token>` header. Simple for programmatic clients. Vulnerable to XSS: any injected script can read and exfiltrate the token.

**Option B — HttpOnly cookies**  
Token is set and read by the server. JavaScript cannot access it. Immune to XSS. Requires CSRF mitigation because cookies are sent automatically on same-origin and cross-site-navigation requests (subject to SameSite policy).

---

## Decision

Use **HttpOnly cookies** for all authentication tokens. Specifically:

| Cookie | Name | HttpOnly | Secure | SameSite | Path |
|---|---|---|---|---|---|
| JWT access token | `es_access` | Yes | Yes (prod) | Lax | `/api/v1` |
| Opaque refresh token | `es_refresh` | Yes | Yes (prod) | Lax | `/api/v1/auth` |
| CSRF token | `es_csrf` | **No** | Yes (prod) | Lax | `/` |

The refresh cookie path is restricted to `/api/v1/auth` so the refresh token is never sent to non-auth endpoints even within the API.

The CSRF cookie is intentionally non-HttpOnly so that the frontend JavaScript can read it and include it in the `X-CSRF-Token` request header. The backend validates that the header value matches the cookie value (double-submit pattern). Because the cookie is SameSite=Lax, a cross-site attacker cannot read the cookie via JavaScript or set the correct header.

Access tokens are delivered **only** via the `es_access` HttpOnly cookie. They are never returned in the JSON response body. This applies to login, refresh, and switch-org. Programmatic clients (CLI tools, testing) must read the cookie.

---

## Consequences

- XSS cannot steal tokens (HttpOnly cookies are inaccessible to JavaScript)
- CSRF is mitigated by the double-submit pattern + SameSite=Lax + Origin header validation
- Next.js middleware can read `es_access` server-side to gate protected routes
- Refresh is transparent to the user (browser sends `es_refresh` automatically)
- Logout must clear all three cookies server-side
- API documentation must note that browser clients use cookies, not Authorization headers

---

## Rejected Alternatives

**localStorage with Authorization headers**: Rejected. XSS vulnerability is unacceptable for a multi-tenant B2B product handling interview data.

**SameSite=Strict**: Rejected. Strict mode breaks OAuth redirect flows required in Milestone 6 (Zoom/Google OAuth). Lax + Origin validation provides equivalent CSRF protection for our use case.

**SameSite=None**: Rejected. Requires Secure=True (acceptable), but allows all cross-site requests (unacceptable). We do not require cross-site cookie sending.
