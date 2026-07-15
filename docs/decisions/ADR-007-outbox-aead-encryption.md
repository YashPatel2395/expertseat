# ADR-007: Outbox Payload Encryption — AES-256-GCM via `cryptography`

**Status:** Accepted  
**Date:** 2026-07-14  
**Deciders:** Engineering  

---

## Context

The transactional email outbox stores invitation tokens and email content in the
database until a background worker delivers them. Email addresses and token values
are authentication secrets; a database-level breach must not expose them in
plaintext.

An initial implementation used a bespoke HMAC-SHA256 + XOR stream cipher.
This was rejected because:

- Custom cipher constructions are not peer-reviewed and frequently contain subtle flaws.
- XOR-based stream ciphers without rigorous security proofs do not meet the standard
  of "authenticated encryption with associated data" (AEAD).
- There is no reviewed security proof that HMAC-SHA256 + XOR in CTR mode provides
  IND-CPA security against arbitrary adversaries.
- The construction was not constant-time in all implementations.

---

## Decision

Use **AES-256-GCM** (Galois/Counter Mode with a 256-bit key) as provided by the
PyCA `cryptography` library, version `>=43.0.0`.

Library: `cryptography==49.0.0` (pinned in `pyproject.toml`).  
API: `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.

### Why AES-256-GCM

| Property | AES-256-GCM |
|---|---|
| Confidentiality | AES-CTR provides IND-CPA |
| Integrity + authenticity | GHASH authentication tag (128 bits) |
| Nonce | 96-bit random, unique per message |
| Tag verification | Constant-time via C extension |
| Library maturity | PyCA cryptography — widely audited, FIPS-validated backend |
| NIST standardisation | SP 800-38D |

ChaCha20-Poly1305 was considered as an alternative. It is equally acceptable
and may be preferred in environments without AES hardware acceleration. AES-256-GCM
was selected because AES-NI is present on all current x86-64 and ARM64 server
processors.

### Why `cryptography` over other options

- `pyca/cryptography` is the de-facto standard Python cryptography library.
- Actively maintained by the Python Cryptographic Authority.
- Has no history of severe vulnerabilities in its AES-GCM implementation.
- Provides a pure-Python hazmat API with clear usage contracts.
- `pip-audit` reports no known CVEs for version 49.0.0.

---

## Encrypted Envelope Format

Every outbox record stores a JSON envelope. The envelope contains only
non-secret metadata; all plaintext is inside the ciphertext:

```json
{
  "v": 1,
  "alg": "AES-256-GCM",
  "kid": "<key-identifier>",
  "nonce": "<base64url-12-bytes>",
  "ct": "<base64url-ciphertext+16-byte-GCM-tag>"
}
```

- `v` — envelope format version (current: 1).
- `alg` — algorithm identifier; parser rejects unknown values.
- `kid` — identifies which key was used for decryption during key rotation.
- `nonce` — 96-bit random nonce; never reused.
- `ct` — `AESGCM.encrypt(nonce, plaintext, None)` output (ciphertext + 128-bit tag).

The authentication tag is the last 16 bytes of `ct`. The AESGCM decryption
function raises `cryptography.exceptions.InvalidTag` if the ciphertext or tag
has been modified; this is caught and re-raised as `ValueError`.

---

## Key Management

### Configuration

`OUTBOX_ENCRYPTION_KEY` — hex-encoded 32-byte (256-bit) key.

```
# Generate:
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Separation requirements:
- Must differ from `SECRET_KEY`.
- Must differ from `RATE_LIMIT_SECRET`.
- Production startup fails if any of these are equal or absent.

### Key identifier

The active key is identified by the `kid` field in `Settings.outbox_active_key_id`
(default: `"v1"`). On decryption, the code resolves `kid` to the correct key bytes.

Currently only the active key is supported. Key history is reserved for a
future structured key-rotation feature (see Rotation Procedure below).

### Rotation Procedure

1. Generate a new key: `python3 -c "import secrets; print(secrets.token_hex(32))"`.
2. Deploy the new key as `OUTBOX_ENCRYPTION_KEY_V2` alongside the current key.
3. Update `Settings.outbox_active_key_id` to `"v2"`.
4. Newly enqueued records use `v2`.
5. The worker retains `v1` for decrypting pending records until the queue drains.
6. Once all `kid="v1"` records are sent or dead, remove the `v1` key.

### Pending records during rotation

Pending outbox records encrypted with the old key remain decryptable as long as
the old key is present in the deployment configuration. They are NOT re-encrypted
automatically. Operators must either:
- Process all pending records before removing the old key, or
- Re-encrypt them via a one-time migration script.

Dead records encrypted with the old key cannot be re-attempted after key removal
without re-encryption. This is documented and acceptable because dead records
represent permanent failures.

---

## Retention Policy

| Status | Retention |
|---|---|
| `pending` | Until delivered or dead |
| `processing` | Max 5 minutes; reverts to `pending` on lock expiry |
| `sent` | 7 days, then eligible for deletion |
| `retry` | Same as pending |
| `dead` | 30 days, then eligible for deletion |

Sent records are deleted by a scheduled cleanup job (`DELETE FROM email_outbox
WHERE status = 'sent' AND sent_at < now() - interval '7 days'`).

Token-bearing payloads (invitation, verification, password-reset) in `sent`
records are already delivered and the tokens have TTLs enforced by business logic
(invitation: 7 days, verification: 24h, password-reset: 30 minutes). The
encrypted payload in a `sent` record after these TTLs contains an expired token —
delivering it again produces an error, not a security breach.

---

## Duplicate-Delivery Policy

The outbox provides **at-least-once delivery**. Exactly-once delivery is not
guaranteed because SMTP does not provide transactional guarantees.

Mitigations:
- Invitation tokens are single-use: acceptance marks the invitation as used.
- Verification tokens are single-use: the first verification succeeds; subsequent
  deliveries of the same token produce a harmless "already verified" error.
- Password-reset tokens are single-use: the first use invalidates the token.
- Each outbox row has a unique `id` that can be used as a provider idempotency key
  when the provider supports it (e.g., SendGrid `X-Message-Id` header).

The duplication window is bounded by the `locked_at` expiry (5 minutes): within
that window, only one worker holds the lock. After expiry, the item reverts to
`pending` for retry; if the first worker also eventually succeeds, the recipient
gets two emails. This is logged and acceptable.

---

## Consequences

- The `cryptography` package is now a required runtime dependency.
- Changing the encryption algorithm requires a migration and re-encryption of
  pending records.
- The OUTBOX_ENCRYPTION_KEY must be managed as a production secret and must
  never be committed to version control.
- A `.env.example` placeholder is provided (never commit the real value).
