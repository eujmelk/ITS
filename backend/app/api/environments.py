"""Environments: one city or operation per database.

Listing is available to anyone signed in — the switcher in the menu bar needs
it. Creating, renaming and deleting are administrator work, because they
provision and destroy databases.
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.deps import AdminUser, ControlDb, CurrentEnvironment, CurrentUser
from app.models import Environment
from app.schemas.environments import (
    EnvironmentCreate,
    EnvironmentRead,
    EnvironmentUpdate,
)
from app.services import environments as environment_service
from app.services.crud import apply_updates, commit, get_or_404

router = APIRouter(prefix="/environments", tags=["environments"])


def _serialize(row: Environment, current_key: str) -> EnvironmentRead:
    data = EnvironmentRead.model_validate(row)
    data.is_current = row.key == current_key
    return data


@router.get("", response_model=list[EnvironmentRead], summary="List environments")
def list_environments(
    control: ControlDb,
    current: CurrentEnvironment,
    _user: CurrentUser,
    include_inactive: bool = False,
):
    """Every environment this login can work in.

    All signed-in users see all environments; the role they hold applies
    everywhere.
    """
    stmt = select(Environment).order_by(Environment.name)
    if not include_inactive:
        stmt = stmt.where(Environment.is_active.is_(True))
    return [_serialize(row, current.key) for row in control.scalars(stmt).all()]


@router.get("/current", response_model=EnvironmentRead, summary="The active environment")
def current_environment(current: CurrentEnvironment, _user: CurrentUser):
    return _serialize(current, current.key)


@router.post(
    "",
    response_model=EnvironmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an environment",
)
def create_environment(payload: EnvironmentCreate, control: ControlDb, _admin: AdminUser):
    """Provisions a database, builds the schema and seeds the parameters.

    This can take a few seconds. The key becomes part of the database name and
    cannot be changed afterwards; the display name can.
    """
    environment = environment_service.create_environment(
        control, payload.key, payload.name, payload.notes
    )
    return _serialize(environment, environment.key)


@router.patch(
    "/{environment_id}", response_model=EnvironmentRead, summary="Rename or disable"
)
def update_environment(
    environment_id: int,
    payload: EnvironmentUpdate,
    control: ControlDb,
    current: CurrentEnvironment,
    _admin: AdminUser,
):
    environment = get_or_404(control, Environment, environment_id, "Environment")

    if payload.is_active is False:
        if environment.is_default:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The default environment cannot be disabled. Make another one "
                "the default first.",
            )
        if environment.key == current.key:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "You are working in this environment. Switch away before "
                "disabling it.",
            )

    apply_updates(environment, payload)
    commit(control)
    control.refresh(environment)
    return _serialize(environment, current.key)


@router.post(
    "/{environment_id}/make-default",
    response_model=EnvironmentRead,
    summary="Use this environment when a request names none",
)
def make_default(
    environment_id: int,
    control: ControlDb,
    current: CurrentEnvironment,
    _admin: AdminUser,
):
    environment = get_or_404(control, Environment, environment_id, "Environment")
    if not environment.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A disabled environment cannot be the default."
        )
    for row in control.scalars(select(Environment)).all():
        row.is_default = row.id == environment.id
    commit(control)
    control.refresh(environment)
    return _serialize(environment, current.key)


@router.delete(
    "/{environment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an environment",
)
def delete_environment(
    environment_id: int,
    control: ControlDb,
    current: CurrentEnvironment,
    _admin: AdminUser,
    drop_data: bool = Query(
        default=False,
        description=(
            "Also DROP the database. Irreversible, and there is no undo — "
            "leave this off to unregister the environment while keeping its "
            "data on disk."
        ),
    ),
):
    """Unregisters the environment, and optionally destroys its database."""
    environment = get_or_404(control, Environment, environment_id, "Environment")
    if environment.key == current.key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You are working in this environment. Switch away before deleting it.",
        )
    environment_service.delete_environment(control, environment, drop_data)


routers: list[APIRouter] = [router]
