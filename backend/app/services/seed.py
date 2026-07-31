"""First-run bootstrap: admin account, parameters, and optional demo data."""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import (
    BlockPieceType,
    LocationType,
    Role,
    TransportMode,
    VersionStatus,
)
from app.models import (
    Block,
    BlockPiece,
    Calendar,
    Driver,
    FareRule,
    FareZone,
    Line,
    LineAttribute,
    Location,
    LocationAttribute,
    LocationTransfer,
    Pattern,
    PatternStop,
    ScheduleVersion,
    StopArea,
    Trip,
    User,
    Vehicle,
    VehicleType,
)
from app.security import hash_password
from app.services.parameters import ensure_seeded
from app.services.trips import generate_stop_times, set_stop_times

log = logging.getLogger(__name__)


def bootstrap(db: Session) -> None:
    _ensure_admin(db)
    added = ensure_seeded(db)
    if added:
        log.info("Seeded %s operating parameters", added)
    if settings.seed_demo_data:
        _seed_demo(db)


def _ensure_admin(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(User)):
        return
    if len(settings.first_admin_password) < 8:
        log.error(
            "FIRST_ADMIN_PASSWORD is shorter than 8 characters; refusing to "
            "create the bootstrap administrator. Set a longer one and restart."
        )
        return
    db.add(
        User(
            username=settings.first_admin_username,
            email=settings.first_admin_email,
            full_name="Administrator",
            role=Role.ADMIN.value,
            is_active=True,
            hashed_password=hash_password(settings.first_admin_password),
        )
    )
    db.commit()
    log.warning(
        "Created bootstrap administrator '%s'. Change this password on first "
        "login.",
        settings.first_admin_username,
    )


def _seed_demo(db: Session) -> None:
    """A small but complete network, so the UI is not empty on first login.

    Skipped entirely if any location already exists -- this is a first-run
    convenience, never something that touches real data.
    """
    if db.scalar(select(func.count()).select_from(Location)):
        return

    log.info("Seeding demo data (SEED_DEMO_DATA=true)")

    zone_a = FareZone(name="Zone A (centre)", code="A")
    zone_b = FareZone(name="Zone B (outer)", code="B")
    db.add_all([zone_a, zone_b])
    db.flush()

    for origin, destination, price in (
        (zone_a, zone_a, 210),
        (zone_a, zone_b, 320),
        (zone_b, zone_a, 320),
        (zone_b, zone_b, 210),
    ):
        db.add(
            FareRule(
                origin_zone_id=origin.id,
                destination_zone_id=destination.id,
                price_cents=price,
                currency="EUR",
                description=f"{origin.code} to {destination.code}",
            )
        )

    # Two stops on opposite sides of the same street: the exact case stop
    # areas exist for.
    central_area = StopArea(
        name="Central Station", default_transfer_seconds=150,
        notes="Opposite sides of the station forecourt.",
    )
    db.add(central_area)
    db.flush()

    depot = Location(
        name="North Depot", code="DEP1", location_type=LocationType.DEPOT.value,
        lat=52.3900, lon=4.8900,
    )
    stops_spec = [
        ("Central Station (eastbound)", "CS-E", 52.3791, 4.9003, zone_a.id, central_area.id),
        ("Central Station (westbound)", "CS-W", 52.3789, 4.9007, zone_a.id, central_area.id),
        ("Market Square", "MKT", 52.3745, 4.8960, zone_a.id, None),
        ("University", "UNI", 52.3680, 4.8890, zone_a.id, None),
        ("Riverside Park", "RIV", 52.3610, 4.8800, zone_b.id, None),
        ("Northgate Interchange", "NGI", 52.3860, 4.8930, zone_b.id, None),
    ]
    db.add(depot)
    stops = []
    for name, code, lat, lon, zone_id, area_id in stops_spec:
        stop = Location(
            name=name, code=code, location_type=LocationType.STOP.value,
            lat=lat, lon=lon, zone_id=zone_id, area_id=area_id,
        )
        db.add(stop)
        stops.append(stop)
    db.flush()

    for stop in stops:
        db.add(LocationAttribute(location_id=stop.id, attribute_key="has_shelter", attribute_value="true"))
        db.add(LocationAttribute(location_id=stop.id, attribute_key="wheelchair_accessible", attribute_value="true"))
    db.add(LocationAttribute(location_id=depot.id, attribute_key="capacity", attribute_value="40"))
    db.add(LocationAttribute(location_id=depot.id, attribute_key="fuel_type_supported", attribute_value="diesel,electric"))

    # An explicit pairwise transfer: not the same place, but a real walk.
    db.add(
        LocationTransfer(
            from_location_id=stops[2].id, to_location_id=stops[3].id,
            walk_seconds=420, distance_m=520, is_bidirectional=True,
            notes="Through the pedestrian precinct.",
        )
    )

    line = Line(
        short_name="4", long_name="Northgate — Riverside",
        mode=TransportMode.BUS.value, color="1F4E79", text_color="FFFFFF",
        sort_order=1,
    )
    db.add(line)
    db.flush()
    db.add(LineAttribute(line_id=line.id, attribute_key="wheelchair_accessible", attribute_value="true"))
    db.add(LineAttribute(line_id=line.id, attribute_key="night_service", attribute_value="false"))

    outbound = Pattern(
        line_id=line.id, name="Northgate to Riverside", direction=0,
        headsign="Riverside Park", is_primary=True,
    )
    inbound = Pattern(
        line_id=line.id, name="Riverside to Northgate", direction=1,
        headsign="Northgate Interchange", is_primary=True,
    )
    db.add_all([outbound, inbound])
    db.flush()

    outbound_stops = [stops[5], stops[0], stops[2], stops[3], stops[4]]
    inbound_stops = [stops[4], stops[3], stops[2], stops[1], stops[5]]
    for pattern, ordered in ((outbound, outbound_stops), (inbound, inbound_stops)):
        for index, stop in enumerate(ordered, start=1):
            db.add(
                PatternStop(
                    pattern_id=pattern.id,
                    sequence=index,
                    location_id=stop.id,
                    is_timepoint=index in (1, 3, len(ordered)),
                    default_run_seconds=0 if index == 1 else 240,
                    default_dwell_seconds=30 if index in (1, len(ordered)) else 0,
                )
            )
    db.flush()

    today = dt.date.today()
    board = ScheduleVersion(
        name=f"Demo board {today.year}",
        description="Seeded example board. Safe to delete.",
        start_date=today,
        end_date=today + dt.timedelta(days=180),
        status=VersionStatus.ACTIVE.value,
    )
    db.add(board)
    db.flush()

    weekday = Calendar(
        schedule_version_id=board.id, name="Weekdays",
        monday=True, tuesday=True, wednesday=True, thursday=True, friday=True,
    )
    weekend = Calendar(
        schedule_version_id=board.id, name="Weekend", saturday=True, sunday=True
    )
    db.add_all([weekday, weekend])
    db.flush()

    created_trips: dict[int, list[Trip]] = {outbound.id: [], inbound.id: []}
    for pattern in (outbound, inbound):
        offset = 0 if pattern.id == outbound.id else 1800
        for departure in range(6 * 3600 + offset, 9 * 3600 + offset + 1, 1800):
            trip = Trip(
                schedule_version_id=board.id,
                pattern_id=pattern.id,
                calendar_id=weekday.id,
                headsign=pattern.headsign,
                short_name=line.short_name,
            )
            db.add(trip)
            db.flush()
            set_stop_times(db, trip, generate_stop_times(db, pattern.id, departure))
            created_trips[pattern.id].append(trip)

    standard = VehicleType(
        name="Standard 12m", code="STD12", capacity_seated=38,
        capacity_standing=32, fuel_type="diesel", length_m=12.0,
    )
    db.add(standard)
    db.flush()
    db.add_all(
        [
            Vehicle(fleet_number="101", vehicle_type_id=standard.id, depot_location_id=depot.id),
            Vehicle(fleet_number="102", vehicle_type_id=standard.id, depot_location_id=depot.id),
        ]
    )

    db.add_all(
        [
            Driver(code="D001", first_name="Alex", last_name="Moreau", base_location_id=depot.id),
            Driver(code="D002", first_name="Sam", last_name="Okonkwo", base_location_id=depot.id),
        ]
    )

    # One worked example of a block. The outbound trip ends at Riverside and
    # the inbound one starts there, so no deadhead is needed between them --
    # which is exactly what the continuity validator checks for.
    block = Block(schedule_version_id=board.id, name="B01", vehicle_type_id=standard.id)
    db.add(block)
    db.flush()

    first_out = created_trips[outbound.id][0]
    first_in = created_trips[inbound.id][0]
    out_times = sorted(first_out.stop_times, key=lambda st: st.arrival_seconds)
    in_times = sorted(first_in.stop_times, key=lambda st: st.arrival_seconds)

    pieces = [
        BlockPiece(
            block_id=block.id, sequence=1, piece_type=BlockPieceType.PULL_OUT.value,
            from_location_id=depot.id, to_location_id=outbound_stops[0].id,
            start_seconds=out_times[0].departure_seconds - 900,
            end_seconds=out_times[0].departure_seconds,
        ),
        BlockPiece(
            block_id=block.id, sequence=2, piece_type=BlockPieceType.TRIP.value,
            trip_id=first_out.id,
        ),
        BlockPiece(
            block_id=block.id, sequence=3, piece_type=BlockPieceType.TRIP.value,
            trip_id=first_in.id,
        ),
        BlockPiece(
            block_id=block.id, sequence=4, piece_type=BlockPieceType.PULL_IN.value,
            from_location_id=inbound_stops[-1].id, to_location_id=depot.id,
            start_seconds=in_times[-1].arrival_seconds,
            end_seconds=in_times[-1].arrival_seconds + 900,
        ),
    ]
    db.add_all(pieces)
    first_out.block_id = block.id
    first_in.block_id = block.id

    db.commit()
    log.info("Demo data seeded: 1 line, 2 patterns, %s trips, 1 block",
             sum(len(v) for v in created_trips.values()))
