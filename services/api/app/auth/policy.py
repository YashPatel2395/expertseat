"""RBAC policy functions.

All role authorization checks use these functions. No role check logic
is duplicated in route handlers.

Role hierarchy (highest → lowest privilege):
  admin > recruiter > reviewer
"""

from fastapi import Depends, HTTPException

from app.auth.deps import WorkspaceContext, get_workspace_context

_ROLE_RANK: dict[str, int] = {
    "admin": 3,
    "recruiter": 2,
    "reviewer": 1,
}


def require_role(minimum_role: str):
    """FastAPI dependency factory.

    Usage:
        @router.post("/endpoint")
        async def handler(_: None = Depends(require_role("admin"))): ...
    """

    async def _check(ctx: WorkspaceContext = Depends(get_workspace_context)) -> None:
        actor_rank = _ROLE_RANK.get(ctx.role, 0)
        required_rank = _ROLE_RANK.get(minimum_role, 999)
        if actor_rank < required_rank:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "INSUFFICIENT_ROLE",
                    "message": f"This action requires the '{minimum_role}' role",
                },
            )

    return _check


def check_can_manage_member(actor_role: str, target_role: str) -> None:
    """Raise if the actor cannot manage a member with the given role.

    Only admins can manage any member. All other roles cannot manage anyone.
    """
    if actor_role != "admin":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "INSUFFICIENT_ROLE",
                "message": "Only admins can manage workspace members",
            },
        )
