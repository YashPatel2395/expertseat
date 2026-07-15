"""Domain exceptions for the refresh token flow.

These are NOT HTTPException subclasses. They are raised by service functions
and caught in route handlers so the route can commit necessary DB state
(e.g., family revocation) before returning an HTTP error response.
"""


class RefreshReplayDetected(Exception):
    """Raised when a refresh token has already been used (replay attack).

    The service DOES mark family members revoked before raising this.
    The route handler MUST commit those revocations, then return 401.
    """

    def __init__(self, family_id: str) -> None:
        self.family_id = family_id
        super().__init__(f"Replay detected for family {family_id}")


class RefreshAccountInvalid(Exception):
    """Raised during refresh when the account/org/membership is invalid.

    Unlike replay, no family revocation is needed — the session simply
    cannot be rotated. The route should clear cookies and return 401/403.
    """

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code}: {message}")


class RefreshAccountDisabled(Exception):
    """Raised during refresh when the user account is disabled.

    The service DOES revoke the session family before raising this exception.
    The route handler MUST commit those revocations, clear cookies, then return 401.

    Unlike RefreshAccountInvalid, this exception signals that family revocation
    has already been staged and must be committed — same pattern as RefreshReplayDetected.
    """

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        super().__init__(f"Account disabled for user {user_id}")
