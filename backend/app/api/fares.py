"""Fares: zones and the origin x destination price matrix."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.deps import DbSession, ReaderUser, require_planner
from app.models import FareRule, FareZone, Location
from app.schemas.fares import (
    FareMatrix,
    FareMatrixCell,
    FareQuote,
    FareRuleCreate,
    FareRuleRead,
    FareRuleUpdate,
    FareZoneCreate,
    FareZoneRead,
    FareZoneUpdate,
)
from app.services.crud import check_exists, commit, crud_router, get_or_404


def serialize_zone(obj: FareZone, db: Session) -> FareZoneRead:
    data = FareZoneRead.model_validate(obj)
    data.location_count = (
        db.scalar(
            select(func.count()).select_from(Location).where(Location.zone_id == obj.id)
        )
        or 0
    )
    return data


def serialize_rule(obj: FareRule, db: Session) -> FareRuleRead:
    data = FareRuleRead.model_validate(obj)
    data.origin_zone_name = obj.origin_zone.name if obj.origin_zone else None
    data.destination_zone_name = (
        obj.destination_zone.name if obj.destination_zone else None
    )
    return data


zones_router = crud_router(
    model=FareZone,
    read_schema=FareZoneRead,
    create_schema=FareZoneCreate,
    update_schema=FareZoneUpdate,
    prefix="/fare-zones",
    tags=["fares"],
    search_fields=("name", "code"),
    order_by=("name",),
    serialize=serialize_zone,
    label="Fare zone",
)


def _rule_on_create(obj: FareRule, payload: FareRuleCreate, db: Session) -> None:
    check_exists(db, FareZone, obj.origin_zone_id, "origin_zone_id")
    check_exists(db, FareZone, obj.destination_zone_id, "destination_zone_id")


rules_router = crud_router(
    model=FareRule,
    read_schema=FareRuleRead,
    create_schema=FareRuleCreate,
    update_schema=FareRuleUpdate,
    prefix="/fare-rules",
    tags=["fares"],
    filter_fields=("origin_zone_id", "destination_zone_id"),
    order_by=("origin_zone_id", "destination_zone_id"),
    options=(
        selectinload(FareRule.origin_zone),
        selectinload(FareRule.destination_zone),
    ),
    serialize=serialize_rule,
    on_create=_rule_on_create,
    label="Fare rule",
)


# Tools live under their own prefix rather than on /fare-rules: the CRUD
# factory already owns /fare-rules/{item_id}, which would swallow a sibling
# path like /fare-rules/quote before it was ever matched.
tools_router = APIRouter(prefix="/fares", tags=["fares"])


def _build_matrix(db: Session) -> FareMatrix:
    zones = db.scalars(select(FareZone).order_by(FareZone.name)).all()
    priced = {
        (rule.origin_zone_id, rule.destination_zone_id): rule
        for rule in db.scalars(select(FareRule)).all()
    }

    cells: list[FareMatrixCell] = []
    missing = 0
    for origin in zones:
        for destination in zones:
            rule = priced.get((origin.id, destination.id))
            if rule is None:
                missing += 1
            cells.append(
                FareMatrixCell(
                    origin_zone_id=origin.id,
                    destination_zone_id=destination.id,
                    rule_id=rule.id if rule else None,
                    price_cents=rule.price_cents if rule else None,
                    currency=rule.currency if rule else None,
                )
            )

    return FareMatrix(
        zone_ids=[z.id for z in zones],
        zone_names=[z.name for z in zones],
        cells=cells,
        missing_count=missing,
    )


@tools_router.get(
    "/matrix",
    response_model=FareMatrix,
    summary="The zone x zone price grid",
)
def fare_matrix(db: DbSession, _user: ReaderUser):
    """Every ordered zone pair, priced or not.

    Same-zone fares are the diagonal -- they need no special rule type.
    ``missing_count`` is what the UI shows as "cells still to price".
    """
    return _build_matrix(db)


@tools_router.post(
    "/matrix/fill",
    response_model=FareMatrix,
    summary="Price every unpriced cell at once",
    dependencies=[Depends(require_planner)],
)
def fill_matrix(
    db: DbSession,
    price_cents: int,
    currency: str = "EUR",
    only_same_zone: bool = False,
):
    """Bulk-fill the gaps, so a new zone does not mean hand-entering a row.

    Existing rules are never overwritten.
    """
    if price_cents < 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "price_cents must not be negative"
        )

    zone_ids = list(db.scalars(select(FareZone.id).order_by(FareZone.id)).all())
    existing = {
        (rule.origin_zone_id, rule.destination_zone_id)
        for rule in db.scalars(select(FareRule)).all()
    }

    for origin in zone_ids:
        for destination in zone_ids:
            if (origin, destination) in existing:
                continue
            if only_same_zone and origin != destination:
                continue
            db.add(
                FareRule(
                    origin_zone_id=origin,
                    destination_zone_id=destination,
                    price_cents=price_cents,
                    currency=currency,
                )
            )
    commit(db)
    return _build_matrix(db)


@tools_router.get(
    "/quote", response_model=FareQuote, summary="Price a journey between two locations"
)
def quote(db: DbSession, _user: ReaderUser, from_location_id: int, to_location_id: int):
    """Look up the fare for an origin/destination pair via their zones."""
    origin = get_or_404(db, Location, from_location_id, "Location")
    destination = get_or_404(db, Location, to_location_id, "Location")

    if origin.zone_id is None or destination.zone_id is None:
        unzoned = origin.name if origin.zone_id is None else destination.name
        return FareQuote(
            origin_zone_id=origin.zone_id,
            destination_zone_id=destination.zone_id,
            matched=False,
            reason=f"'{unzoned}' is not assigned to a fare zone.",
        )

    rule = db.scalar(
        select(FareRule)
        .where(FareRule.origin_zone_id == origin.zone_id)
        .where(FareRule.destination_zone_id == destination.zone_id)
    )
    if rule is None:
        return FareQuote(
            origin_zone_id=origin.zone_id,
            destination_zone_id=destination.zone_id,
            matched=False,
            reason="No fare rule covers this zone pair.",
        )

    return FareQuote(
        origin_zone_id=origin.zone_id,
        destination_zone_id=destination.zone_id,
        price_cents=rule.price_cents,
        currency=rule.currency,
        rule_id=rule.id,
        matched=True,
    )


routers: list[APIRouter] = [zones_router, rules_router, tools_router]
