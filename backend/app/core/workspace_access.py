"""Personal workspace authorization; always evaluates persisted session identity."""
from fastapi import Depends, HTTPException
from app.core.auth_deps import current_user
from app.models import User


def workspace_enabled(user: User) -> bool:
    return bool(user.is_active and user.role == "admin" and user.email == "ronak@6thsense.dev")


async def workspace_owner(user: User = Depends(current_user)) -> User:
    if not workspace_enabled(user):
        raise HTTPException(status_code=403, detail="Workspace is not enabled for this account.")
    return user
