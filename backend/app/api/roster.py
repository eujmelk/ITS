"""Roster module.

Scope note: this build covers phases 1-9. Drivers are live, because they are
reference data the rest of the system already wants. The duty builder itself
(phase 10) is stubbed -- but the request and response models below are the
real ones, and the tables already exist in the database, so completing it is
filling in handlers rather than redesigning a contract.

Every stub returns 501 with a message saying so, rather than an empty 200
that would look like "no duties exist yet".
"""

import datetime as dt

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.deps import DbSession, ReaderUser
from app.models import Driver, Location
from app.schemas.common import ValidationReport
from app.schemas.roster import (
    BlockCoverage,
    DriverCreate,
    DriverRead,
    DriverUpdate,
    DutyCreate,
    DutyDetail,
    DutyPiecesReplace,
    DutyRead,
    DutyUpdate,
)
from app.services.crud import check_exists, crud_router

_NOT_YET = (
    "The duty builder is phase 10 and is not implemented in this build. "
    "The duties and duty_pieces tables exist and this endpoint's request and "
    "response models are final, so no client change will be needed when it "
    "lands."
)


def serialize_driver(obj: Driver, db: Session) -> DriverRead:
    data = DriverRead.model_validate(obj)
    data.display_name = obj.display_name
    data.base_location_name = obj.base_location.name if obj.base_location else None
    return data


def _driver_check(obj: Driver, payload, db: Session) -> None:
    if obj.base_location_id is not None:
        check_exists(db, Location, obj.base_location_id, "base_location_id")


drivers_router = crud_router(
    model=Driver,
    read_schema=DriverRead,
    create_schema=DriverCreate,
    update_schema=DriverUpdate,
    prefix="/drivers",
    tags=["roster"],
    search_fields=("code", "first_name", "last_name", "email"),
    filter_fields=("is_active", "base_location_id"),
    order_by=("last_name", "first_name"),
    options=(selectinload(Driver.base_location),),
    serialize=serialize_driver,
    on_create=_driver_check,
    on_update=_driver_check,
    label="Driver",
)

# --------------------------------------------------------------------------
# Duties -- contract fixed, handlers pending (phase 10)
# --------------------------------------------------------------------------

duties_router = APIRouter(prefix="/duties", tags=["roster"])


def _not_implemented() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, _NOT_YET)


@duties_router.get("", response_model=list[DutyRead], summary="List duties (phase 10)")
def list_duties(
    db: DbSession,
    _user: ReaderUser,
    schedule_version_id: int | None = None,
    date: dt.date | None = None,
    driver_id: int | None = None,
):
    _not_implemented()


@duties_router.post(
    "", response_model=DutyDetail, status_code=status.HTTP_201_CREATED,
    summary="Create a duty (phase 10)",
)
def create_duty(payload: DutyCreate, db: DbSession, _user: ReaderUser):
    _not_implemented()


@duties_router.get(
    "/{duty_id}", response_model=DutyDetail, summary="Duty with its pieces (phase 10)"
)
def get_duty(duty_id: int, db: DbSession, _user: ReaderUser):
    _not_implemented()


@duties_router.patch(
    "/{duty_id}", response_model=DutyDetail, summary="Update a duty (phase 10)"
)
def update_duty(duty_id: int, payload: DutyUpdate, db: DbSession, _user: ReaderUser):
    _not_implemented()


@duties_router.put(
    "/{duty_id}/pieces",
    response_model=DutyDetail,
    summary="Replace a duty's pieces (phase 10)",
)
def replace_duty_pieces(
    duty_id: int, payload: DutyPiecesReplace, db: DbSession, _user: ReaderUser
):
    _not_implemented()


@duties_router.get(
    "/{duty_id}/validate",
    response_model=ValidationReport,
    summary="Check a duty against the operating parameters (phase 10)",
)
def validate_duty(duty_id: int, db: DbSession, _user: ReaderUser):
    """Will check max driving time, minimum break, continuous-driving limit
    and duty length against ``parameters``, reporting rather than blocking.
    """
    _not_implemented()


@duties_router.get(
    "/coverage/report",
    response_model=list[BlockCoverage],
    summary="Which block pieces still have no driver (phase 10)",
)
def block_coverage(
    db: DbSession, _user: ReaderUser, schedule_version_id: int, date: dt.date
):
    _not_implemented()


routers: list[APIRouter] = [drivers_router, duties_router]
