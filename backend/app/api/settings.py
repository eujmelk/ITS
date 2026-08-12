"""Settings: the global operating parameters the roster validates against."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.deps import DbSession, ReaderUser, require_admin
from app.models import Parameter
from app.schemas.settings import ParameterCreate, ParameterRead, ParameterUpdate
from app.services import parameters as parameter_service
from app.services.crud import apply_updates, commit, get_or_404

router = APIRouter(prefix="/parameters", tags=["settings"])


@router.get("", response_model=list[ParameterRead], summary="List all parameters")
def list_parameters(db: DbSession, _user: ReaderUser):
    """Everything the rule checks read, with its description and unit."""
    return db.scalars(select(Parameter).order_by(Parameter.key)).all()


@router.get("/effective", response_model=dict, summary="Resolved parameter values")
def effective_parameters(db: DbSession, _user: ReaderUser):
    """Values as the validators see them, cast to their declared types.

    Falls back to the built-in default for any key with no row, so a missing
    row can never silently disable a rule.
    """
    return parameter_service.resolve_all(db)


@router.post(
    "",
    response_model=ParameterRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a parameter",
    dependencies=[Depends(require_admin)],
)
def create_parameter(payload: ParameterCreate, db: DbSession):
    if db.get(Parameter, payload.key) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Parameter '{payload.key}' already exists"
        )
    row = Parameter(**payload.model_dump())
    db.add(row)
    commit(db)
    return row


@router.patch(
    "/{key}",
    response_model=ParameterRead,
    summary="Change a parameter's value",
    dependencies=[Depends(require_admin)],
)
def update_parameter(key: str, payload: ParameterUpdate, db: DbSession):
    row = get_or_404(db, Parameter, key, "Parameter")
    apply_updates(row, payload)
    _validate_value(row)
    commit(db)
    return row


@router.delete(
    "/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a parameter",
    dependencies=[Depends(require_admin)],
)
def delete_parameter(key: str, db: DbSession):
    row = get_or_404(db, Parameter, key, "Parameter")
    if key in parameter_service.PARAMETER_SPECS_BY_KEY:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{key}' is a built-in parameter that the rule checks depend on. "
            "Change its value instead of deleting it.",
        )
    db.delete(row)
    commit(db)


@router.post(
    "/reset-defaults",
    response_model=list[ParameterRead],
    summary="Restore built-in parameters that were removed",
    dependencies=[Depends(require_admin)],
)
def reset_defaults(db: DbSession):
    """Re-insert any missing built-in rows. Existing values are untouched."""
    parameter_service.ensure_seeded(db)
    return db.scalars(select(Parameter).order_by(Parameter.key)).all()


#: Blank here would leave the UI with no name at all.
_REQUIRED_NON_EMPTY = {"instance_name", "agency_timezone"}


def _validate_value(row: Parameter) -> None:
    if row.key in _REQUIRED_NON_EMPTY and not (row.value or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"'{row.key}' cannot be empty.",
        )
    if row.value_type in ("int", "float"):
        try:
            float(row.value)
        except (TypeError, ValueError):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"'{row.value}' is not a valid {row.value_type} for '{row.key}'.",
            ) from None
    if row.value_type == "bool" and str(row.value).lower() not in (
        "true",
        "false",
        "1",
        "0",
        "yes",
        "no",
        "on",
        "off",
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"'{row.value}' is not a valid boolean for '{row.key}'.",
        )


routers: list[APIRouter] = [router]
