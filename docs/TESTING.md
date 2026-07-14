# ExpertSeat — Testing Guide

## Quick start

```bash
# All tests (unit + integration)
cd services/api
uv run pytest -v

# Unit tests only (no DB/Redis required)
uv run pytest tests/unit/ -v

# Integration tests only
uv run pytest tests/integration/ -v
```

## Test categories

| Directory | Requires | Marker |
|---|---|---|
| `tests/unit/` | Nothing | _(none)_ |
| `tests/integration/` | PostgreSQL + Redis | `@pytest.mark.integration` |
| `tests/test_*.py` (root) | Nothing | _(none)_ |

---

## Integration test infrastructure

### PostgreSQL

Integration tests run against a **real PostgreSQL database**.  Tables are
created by running `alembic upgrade head` at the start of the test session
(the `run_migrations` session-scoped fixture handles this automatically).

The database URL defaults to:

```
postgresql://expertseat:expertseat_dev@localhost:5432/expertseat
```

Override via `DATABASE_URL` environment variable.

### Redis

Rate-limiting uses a real Redis instance. The `clear_rate_limits` autouse
fixture deletes all `rate:*` keys before each test so that counters do not
accumulate across tests (all TestClient requests share the synthetic IP
`testclient`).

The Redis URL defaults to `redis://localhost:6379`. For stronger isolation,
point it at a dedicated test database:

```bash
export REDIS_URL=redis://localhost:6379/1
```

---

## Transaction isolation: the savepoint model

This is the most important concept in the test infrastructure.

### Problem

Integration tests write data (users, orgs, sessions) that must not persist
between tests.  Naively truncating tables after every test is slow.  Wrapping
each test in a `BEGIN … ROLLBACK` is fast, but FastAPI route handlers call
`db.commit()` internally — and a real `COMMIT` would break the outer
`ROLLBACK`.

### Solution

The `db_session` fixture uses SQLAlchemy 2.0's
`join_transaction_mode="create_savepoint"`:

```python
connection = engine.connect()
transaction = connection.begin()          # outer TX — never committed
session = SASession(
    bind=connection,
    join_transaction_mode="create_savepoint",
)
```

With this mode, every `session.commit()` call inside a route handler issues a
`SAVEPOINT RELEASE sp1` rather than a real `COMMIT`.  The outer transaction
remains open.  At the end of each test, `transaction.rollback()` discards
everything.

### What this means in practice

- Route-level `db.commit()` calls are safe and tested exactly as in production.
- Data written by one test is completely invisible to the next test.
- No table truncation — rollback is O(1) regardless of how much data was written.
- `db_session` in the test and the route handler share the same connection, so
  writes from route handlers are immediately visible to `db_session` queries.

### Known limitation: `func.now()` is frozen

PostgreSQL's `now()` (used as `server_default` on `created_at` columns) returns
the **transaction start timestamp**, not the wall-clock time.  Within a single
test, all rows get the same `created_at` value.

Consequence: tests that rely on `ORDER BY created_at DESC` to determine which
of two rows is "more recent" are non-deterministic when both rows are created
in the same test.

Workaround: use `db_session` to manually backdate one row's `created_at` before
querying, making the ordering deterministic.  See
`test_session_context.py::test_login_with_multiple_memberships_selects_most_recent`
for an example.

---

## Password hashing

Argon2id with production parameters takes ~100 ms per hash.  The conftest
monkey-patches the hasher with low-cost parameters before any app code is
imported:

```python
import app.auth.crypto as _crypto_module
_crypto_module.password_hasher = PasswordHasher(
    time_cost=1, memory_cost=8, parallelism=1, hash_len=16, salt_len=8
)
```

This must happen before any `from app.auth.crypto import password_hasher`
resolves in the process.

---

## Email

Integration tests use `FakeEmailProvider`, injected via FastAPI's dependency
override system.  The fake records all outbound emails in memory.

Use the **typed helpers** to look up emails — do not rely on `last_to()` ordering
when multiple emails go to the same address:

```python
fake_email.verification_message_for("user@example.com")   # kind="verification"
fake_email.invitation_message_for("user@example.com")      # kind="invitation"
fake_email.password_reset_message_for("user@example.com")  # kind="password_reset"
```

The `kind` parameter is threaded through every `provider.send()` call in the
service layer and stored on each `SentEmail` record.

---

## Test file layout

```
tests/
├── unit/
│   ├── test_email_fake.py     # FakeEmailProvider unit tests
│   └── test_orm_fk.py         # ORM ForeignKey declaration tests (no DB)
├── integration/
│   ├── conftest.py            # fixtures: db_session, http_client, fake_email, clear_rate_limits
│   ├── test_auth.py           # core auth flows (register, login, logout, etc.)
│   ├── test_db_fixture.py     # savepoint isolation regression tests
│   ├── test_email_verification.py
│   ├── test_password_reset.py
│   ├── test_ratelimit.py      # Redis rate-limit tests
│   ├── test_refresh_rotation.py  # token rotation & replay detection
│   ├── test_registration_invariant.py  # atomic registration invariants
│   ├── test_session_context.py   # nullable session org context states
│   ├── test_tenant_isolation.py
│   ├── test_workspace.py
│   ├── test_members.py
│   └── test_audit.py
├── test_config.py
├── test_health.py
└── test_regression.py
```
