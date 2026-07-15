# ADR-005: Password Hashing Algorithm

**Status**: Accepted  
**Date**: 2026-07-13  
**Milestone**: 1

---

## Context

User passwords must be stored in a way that makes offline brute-force and dictionary attacks computationally prohibitive, even if the database is compromised.

Requirements:
- Resistant to GPU-accelerated cracking (memory-hard)
- OWASP-recommended parameters
- Python ecosystem support
- Configurable cost parameters (different for production vs. tests)

Candidates:
- **Argon2id** — OWASP first choice, winner of the Password Hashing Competition, memory-hard, time-hard, parallelism-tunable
- **bcrypt** — widely deployed, time-hard but not memory-hard; vulnerable to ASIC acceleration
- **scrypt** — memory-hard, but less flexible than Argon2; slower Python support
- **PBKDF2-SHA256** — FIPS-compliant but weakest of the four; not memory-hard

---

## Decision

Use **Argon2id** via the `argon2-cffi` library.

### Production parameters (OWASP minimum for interactive login, 2024)

```python
PasswordHasher(
    time_cost=2,         # 2 iterations
    memory_cost=65536,   # 64 MiB
    parallelism=2,       # 2 threads
    hash_len=32,         # 32-byte output
    salt_len=16,         # 16-byte random salt
    encoding="utf-8",
)
```

These parameters are chosen to target approximately 100–300 ms hash time on a single modern CPU core, which is acceptable for interactive login while being expensive for offline cracking.

### Test parameters (speed-optimized, injected via conftest)

```python
PasswordHasher(
    time_cost=1,
    memory_cost=8,
    parallelism=1,
    hash_len=16,
    salt_len=8,
)
```

Integration tests inject a `PasswordHasher` instance via a module-level override or pytest fixture. This ensures tests complete in milliseconds while still testing the same code paths.

### Rehash on login

`argon2-cffi` provides `ph.check_needs_rehash(stored_hash)`. On every successful login, if the stored hash was created with different parameters (e.g., after a parameter upgrade), the password is rehashed with the current parameters and the new hash is saved. This allows seamless parameter upgrades without requiring users to reset their passwords.

### Usage

```python
# Hash at registration
hashed = ph.hash(password)

# Verify at login
try:
    ph.verify(hashed, password)
    if ph.check_needs_rehash(hashed):
        user.hashed_password = ph.hash(password)
        db.commit()
except VerifyMismatchError:
    raise InvalidCredentials()
```

---

## Consequences

- Argon2id is the strongest password hashing algorithm available in the Python ecosystem
- 64 MiB memory usage per hash computation is a meaningful defense against GPU cracking farms
- Login will take 100–300 ms per attempt on the server (acceptable; rate limiting is the primary defense against brute force at the API layer)
- Tests use a low-cost hasher override to avoid 100 ms+ waits per test case
- `argon2-cffi` added to `pyproject.toml` dependencies (C extension, compiled at install time)

---

## Rejected Alternatives

**bcrypt**: Rejected. Not memory-hard. GPU implementations (hashcat on bcrypt) are significantly faster than Argon2id.

**scrypt**: Considered. Memory-hard, but Argon2id offers the same properties with better configurability and is the explicit OWASP first recommendation since 2022.

**PBKDF2-SHA256**: Rejected. Not memory-hard. The default Django hasher — adequate for compliance but weaker than Argon2id or bcrypt under GPU attack.
