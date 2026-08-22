from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import ControlSession, get_control_db, session_for
from app.enums import Role
from app.models import Environment, User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/login")

#: Users and the environment registry: shared across every city.
ControlDb = Annotated[Session, Depends(get_control_db)]

#: Header naming the environment. Absent means "the default one", so existing
#: clients and curl one-liners keep working.
ENVIRONMENT_HEADER = "X-Environment"

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def resolve_environment(request: Request) -> Environment:
    """Which environment this request is for.

    Read from the ``X-Environment`` header, falling back to the default. The
    lookup is on the control database and is deliberately strict: an unknown
    or disabled key is an error, never a silent fall-back to another city's
    data.
    """
    key = request.headers.get(ENVIRONMENT_HEADER, "").strip()
    control = ControlSession()
    try:
        if key:
            environment = control.scalar(select(Environment).where(Environment.key == key))
            if environment is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"Unknown environment '{key}'."
                )
        else:
            environment = control.scalar(
                select(Environment)
                .where(Environment.is_default.is_(True))
                .where(Environment.is_active.is_(True))
            ) or control.scalar(
                select(Environment)
                .where(Environment.is_active.is_(True))
                .order_by(Environment.id)
            )
            if environment is None:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "No environment has been created yet.",
                )

        if not environment.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Environment '{environment.key}' is disabled.",
            )

        # Detached copy: the control session closes here, but callers still
        # want the key and database name.
        control.expunge(environment)
        return environment
    finally:
        control.close()


CurrentEnvironment = Annotated[Environment, Depends(resolve_environment)]


def get_db(environment: CurrentEnvironment) -> Iterator[Session]:
    """Session on the requested environment's database.

    Every existing router and service takes this unchanged — which is the
    point of isolating by database rather than by a filter each query has to
    remember.
    """
    db = session_for(environment.database_name)
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], control: ControlDb
) -> User:
    """Users live in the control database, so one login reaches every city."""
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise _CREDENTIALS_ERROR from None

    username = payload.get("sub")
    if not username:
        raise _CREDENTIALS_ERROR

    user = control.scalar(select(User).where(User.username == username))
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
#: Only admins touch users, environments and system parameters.
require_admin = require_roles(Role.ADMIN)

ReaderUser = Annotated[User, Depends(require_reader)]
PlannerUser = Annotated[User, Depends(require_planner)]
AdminUser = Annotated[User, Depends(require_admin)]
