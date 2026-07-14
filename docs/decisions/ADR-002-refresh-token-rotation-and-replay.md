# ADR-002: Refresh Token Rotation and Replay Detection

**Status**: Accepted  
**Date**: 2026-07-13  
**Milestone**: 1

---

## Context

Refresh tokens are long-lived (14 days) and provide the ability to issue new access tokens without re-authentication. If a refresh token is stolen, the attacker has up to 14 days of access. The threat model includes:

- **Token exfiltration via network sniffing** (mitigated by HTTPS)
- **Token exfiltration via server-side logging** (mitigated by only storing the hash)
- **Token theft from a compromised client device**
- **Token theft from the database** (attacker reads `refresh_token_hash`)

The question is: what happens when a refresh token is presented more than once?

---

## Decision

Use **opaque refresh token rotation with family-based replay detection**.

### Token generation

`secrets.token_bytes(32)` → 32 bytes of cryptographic randomness (256-bit entropy). Hex-encoded to a 64-character string for the cookie value.

### Storage

Only the SHA-256 hash is stored: `hashlib.sha256(token_bytes).hexdigest()`. The plaintext token never touches the database. If the database is compromised, the attacker has only hashes, which cannot be reversed to valid tokens.

### Rotation on every use

Every successful call to `POST /api/v1/auth/refresh`:
1. Looks up the `AuthSession` row matching the presented token's SHA-256 hash
2. Sets `revoked_at = now()` on the old row (preserving its `refresh_token_hash` for replay detection)
3. Inserts a **new `AuthSession` row** with the same `family_id`, a new `id`, and the new token hash
4. Sets a new `es_refresh` cookie pointing to the new token

**Why a new row, not an in-place update?** In-place update overwrites the old hash, so a replayed (rotated-out) token produces `INVALID_REFRESH_TOKEN` rather than `REFRESH_TOKEN_REUSED`. Preserving the old row and its hash is what enables replay detection: the lookup finds the revoked-but-matched row and can distinguish "never existed" from "already rotated".

The old token becomes invalid immediately. The window where both old and new tokens are valid is zero.

### Family tracking and replay detection

Every session row has a `family_id` (UUID assigned at login and never changed). All rotations of a session share the same `family_id`.

When a refresh token is presented:
1. The system looks for any `AuthSession` where `refresh_token_hash = sha256(token)`.
2. If found but `revoked_at IS NOT NULL`, this is a **replay** of a rotated token:
   - The entire family is revoked: `UPDATE auth_sessions SET revoked_at = now() WHERE family_id = $1 AND revoked_at IS NULL`
   - The response is 401 REFRESH_TOKEN_REUSED
3. If not found at all, the response is 401 INVALID_REFRESH_TOKEN (token was never issued or was already expired and purged).
4. If found and `revoked_at IS NULL`, rotation proceeds normally.

This means if an attacker steals a refresh token and the legitimate client refreshes first, the next attacker request triggers family revocation and both sessions are destroyed. If the attacker refreshes first, the legitimate client's next request triggers family revocation and the user must re-authenticate.

### Race condition handling

Two concurrent refresh requests from the same client (e.g., two browser tabs) will race. The `AuthSession` row is fetched with `SELECT ... FOR UPDATE` before any state change. The loser acquires the lock after the winner has already set `revoked_at`, so the loser sees a revoked row and triggers family revocation, forcing re-login. This is an acceptable trade-off: race conditions on refresh are extremely rare in practice, and the security benefit of replay detection outweighs the UX cost of an occasional re-login.

The `SELECT FOR UPDATE` also prevents a subtle TOCTOU window: without the lock, two concurrent requests could both read the token as unrevoked, both proceed to rotate, and produce two new children from the same parent — breaking the single-chain invariant.

---

## Consequences

- Stolen refresh tokens become useless after the legitimate client rotates once
- Replay detection provides a signal that a token may have been stolen
- Race conditions on concurrent refresh can log out the user (rare but possible)
- The `family_id` column is required in the schema; additional index on `family_id` for fast family revocation

---

## Rejected Alternatives

**No rotation (static refresh tokens)**: Rejected. Stolen token is valid for 14 days with no recourse short of logout-all.

**Rotation without replay detection**: Rejected. Attacker who steals and uses a token can do so silently. The legitimate client's next rotation invalidates the attacker's token but the attacker already had a window of undetected access.

**Per-request rotation with sliding expiry**: Considered. Adds complexity (each API request rotates a token) with minimal security benefit over the current rotation-on-refresh approach. Rejected.
