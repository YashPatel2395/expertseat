"""Password hashing with Argon2id.

Production parameters (OWASP minimum for interactive login, 2024):
  time_cost=2, memory_cost=65536 (64 MiB), parallelism=2

Test parameters are injected via the `password_hasher` module-level
variable replacement in conftest. Never use production parameters in
tests — they add 100–300 ms per hash and make test suites unacceptably slow.
"""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Module-level hasher — tests may override this via monkeypatch.
password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    encoding="utf-8",
)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Return True if the password matches the hash.

    Raises nothing — callers get a bool. VerifyMismatchError is
    caught here; all other argon2 exceptions propagate (they indicate
    a corrupted hash, which is a programming error).
    """
    try:
        return password_hasher.verify(stored_hash, password)
    except VerifyMismatchError:
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Return True if the hash was made with outdated parameters."""
    return password_hasher.check_needs_rehash(stored_hash)


def sha256_hex(data: bytes) -> str:
    """SHA-256 hash of bytes, returned as a lowercase hex string."""
    return hashlib.sha256(data).hexdigest()


def sha256_of_string(s: str) -> str:
    """SHA-256 hash of a UTF-8 string, returned as a lowercase hex string."""
    return sha256_hex(s.encode("utf-8"))


def generate_token_hex(nbytes: int = 32) -> str:
    """Generate a cryptographically random hex string (2*nbytes chars)."""
    return secrets.token_hex(nbytes)


def generate_token_bytes(nbytes: int = 32) -> bytes:
    """Generate cryptographically random bytes."""
    return secrets.token_bytes(nbytes)
