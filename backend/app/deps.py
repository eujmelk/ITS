from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.enums import Role
from app.models import User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/login")

DbSession = Annotated[Session, Depends(get_db)]

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: DbSession
) -> User:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise _CREDENTIALS_ERROR from None

    username = payload.get("sub")
    if not username:
        raise _CREDENTIALS_ERROR

    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    """Dependency factory guarding an endpoint by role."""

    allowed = {r.value for r in roles}

    def _guard(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Requires one of: {', '.join(sorted(allowed))}. "
                    f"You are '{user.role}'."
                ),
            )
        return user

    return _guard


#: Anyone logged in may read.
require_reader = require_roles(Role.ADMIN, Role.PLANNER, Role.VIEWER)
#: Planners and admins may change planning data.
require_planner = require_roles(Role.ADMIN, Role.PLANNER)
#: Only admins touch users and system parameters.
require_admin = require_roles(Role.ADMIN)

ReaderUser = Annotated[User, Depends(require_reader)]
PlannerUser = Annotated[User, Depends(require_planner)]
AdminUser = Annotated[User, Depends(require_admin)]
