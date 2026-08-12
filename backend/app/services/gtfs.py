"""GTFS feed export.

GTFS is what journey planners, passenger apps and most downstream tooling
consume, so being able to hand one over is the difference between this being
an internal planning database and being the source of truth for the network.

The mapping is close to one-to-one, because the v3 model was already shaped
like GTFS: patterns are trips' stop sequences, stop areas are
``parent_station``, calendars are ``calendar.txt``, and the fare zone matrix
is exactly ``fare_rules.txt``. The places it is *not* one-to-one are
commented below.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import BoardingType, ExceptionType, LocationType, TransportMode
from app.models import (
    Calendar,
    CalendarException,
    FareRule,
    FareZone,
    Line,
    Location,
    LocationTransfer,
    Pattern,
    PatternStop,
    ScheduleVersion,
    StopArea,
    StopTime,
    Trip,
)
from app.services.parameters import resolve_text
from app.timeutil import format_time

#: GTFS route_type. Anything not listed rides as a bus, which is the safest
#: default for a reader that does not recognise the mode.
ROUTE_TYPES = {
    TransportMode.TRAM.value: 0,
    TransportMode.METRO.value: 1,
    TransportMode.RAIL.value: 2,
    TransportMode.BUS.value: 3,
    TransportMode.FERRY.value: 4,
    TransportMode.OTHER.value: 3,
}

#: GTFS pickup_type / drop_off_type.
BOARDING_CODES = {
    BoardingType.REGULAR.value: "0",
    BoardingType.NONE.value: "1",
    BoardingType.PHONE_AGENCY.value: "2",
    BoardingType.COORDINATE_WITH_DRIVER.value: "3",
}

AGENCY_ID = "1"


def _date(value: dt.date) -> str:
    return value.strftime("%Y%m%d")


class _Feed:
    """Collects CSV files, then zips them."""

    def __init__(self) -> None:
        self._files: dict[str, str] = {}

    def add(self, name: str, header: list[str], rows: list[list]) -> None:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
        self._files[name] = buffer.getvalue()

    def to_zip(self) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in self._files.items():
                archive.writestr(name, content)
        return out.getvalue()

    @property
    def names(self) -> list[str]:
        return sorted(self._files)


def export_feed(db: Session, schedule_version_id: int) -> tuple[bytes, str]:
    """Build a GTFS zip for one schedule board. Returns (bytes, filename)."""
    board = db.get(ScheduleVersion, schedule_version_id)
    if board is None:
        raise ValueError(f"Schedule board {schedule_version_id} not found")

    feed = _Feed()
    instance_name = resolve_text(db, "instance_name", "Transit")
    agency_name = resolve_text(db, "agency_name", instance_name)

    # --- agency.txt --------------------------------------------------------
    feed.add(
        "agency.txt",
        ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang", "agency_phone"],
        [
            [
                AGENCY_ID,
                agency_name,
                resolve_text(db, "agency_url", "https://example.invalid"),
                resolve_text(db, "agency_timezone", "UTC"),
                resolve_text(db, "agency_lang", "en"),
                resolve_text(db, "agency_phone", ""),
            ]
        ],
    )

    # --- stops.txt ---------------------------------------------------------
    # Only locations a passenger can use. Depots, garages and layover points
    # are operational and have no place in a public feed -- but a stop area
    # becomes a parent station, which is exactly what GTFS uses it for.
    areas = db.scalars(select(StopArea).order_by(StopArea.id)).all()
    stop_rows: list[list] = []
    for area in areas:
        members = [
            loc
            for loc in db.scalars(
                select(Location)
                .where(Location.area_id == area.id)
                .where(Location.location_type == LocationType.STOP.value)
            ).all()
            if loc.lat is not None and loc.lon is not None
        ]
        if not members:
            continue
        # A parent station needs coordinates; the centroid of its members is
        # the honest answer when nobody has given the station its own.
        stop_rows.append(
            [
                f"A{area.id}",
                "",
                area.name,
                round(sum(m.lat for m in members) / len(members), 6),
                round(sum(m.lon for m in members) / len(members), 6),
                "1",  # location_type 1 = station
                "",
                "",
            ]
        )

    served_stops = db.scalars(
        select(Location)
        .where(Location.location_type == LocationType.STOP.value)
        .order_by(Location.id)
    ).all()
    skipped_no_coords = 0
    for stop in served_stops:
        if stop.lat is None or stop.lon is None:
            # A stop with no coordinates is not loadable by any GTFS reader.
            skipped_no_coords += 1
            continue
        stop_rows.append(
            [
                f"S{stop.id}",
                stop.code or "",
                stop.name,
                round(stop.lat, 6),
                round(stop.lon, 6),
                "0",
                f"A{stop.area_id}" if stop.area_id else "",
                stop.zone_id or "",
            ]
        )
    feed.add(
        "stops.txt",
        ["stop_id", "stop_code", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station", "zone_id"],
        stop_rows,
    )

    # --- routes.txt --------------------------------------------------------
    lines = db.scalars(select(Line).order_by(Line.sort_order, Line.short_name)).all()
    feed.add(
        "routes.txt",
        ["route_id", "agency_id", "route_short_name", "route_long_name", "route_desc", "route_type", "route_color", "route_text_color"],
        [
            [
                line.id,
                AGENCY_ID,
                line.short_name,
                line.long_name or "",
                (line.description or "").replace("\n", " "),
                ROUTE_TYPES.get(line.mode, 3),
                line.color or "",
                line.text_color or "",
            ]
            for line in lines
            if line.is_active
        ],
    )

    # --- calendar.txt / calendar_dates.txt ---------------------------------
    calendars = db.scalars(
        select(Calendar).where(Calendar.schedule_version_id == schedule_version_id)
    ).all()
    feed.add(
        "calendar.txt",
        ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
        [
            [
                calendar.id,
                int(calendar.monday), int(calendar.tuesday), int(calendar.wednesday),
                int(calendar.thursday), int(calendar.friday), int(calendar.saturday),
                int(calendar.sunday),
                _date(calendar.start_date or board.start_date),
                _date(calendar.end_date or board.end_date),
            ]
            for calendar in calendars
        ],
    )

    calendar_ids = [c.id for c in calendars]
    exceptions = []
    if calendar_ids:
        exceptions = db.scalars(
            select(CalendarException).where(CalendarException.calendar_id.in_(calendar_ids))
        ).all()
    feed.add(
        "calendar_dates.txt",
        ["service_id", "date", "exception_type"],
        [
            [
                row.calendar_id,
                _date(row.date),
                1 if row.exception_type == ExceptionType.ADDED.value else 2,
            ]
            for row in exceptions
        ],
    )

    # --- trips.txt ---------------------------------------------------------
    trips = db.scalars(
        select(Trip).where(Trip.schedule_version_id == schedule_version_id).order_by(Trip.id)
    ).all()
    patterns = {
        p.id: p for p in db.scalars(select(Pattern)).all()
    }
    feed.add(
        "trips.txt",
        ["route_id", "service_id", "trip_id", "trip_headsign", "trip_short_name", "direction_id", "block_id", "wheelchair_accessible"],
        [
            [
                patterns[trip.pattern_id].line_id,
                trip.calendar_id,
                trip.id,
                trip.headsign or "",
                trip.short_name or "",
                patterns[trip.pattern_id].direction,
                trip.block_id or "",
                # GTFS: 0 unknown, 1 accessible, 2 not.
                "" if trip.wheelchair_accessible is None else (1 if trip.wheelchair_accessible else 2),
            ]
            for trip in trips
            if trip.pattern_id in patterns
        ],
    )

    # --- stop_times.txt ----------------------------------------------------
    # `stop_sequence` is renumbered per trip rather than reusing the pattern
    # sequence, because a trip that skips stops would otherwise emit gaps --
    # legal in GTFS, but readers differ on how they treat them, and a dense
    # sequence is unambiguous.
    trip_ids = [t.id for t in trips]
    stop_time_rows: list[list] = []
    if trip_ids:
        rows = db.execute(
            select(
                StopTime.trip_id,
                PatternStop.sequence,
                PatternStop.location_id,
                StopTime.arrival_seconds,
                StopTime.departure_seconds,
                StopTime.is_timepoint,
                StopTime.pickup_type,
                StopTime.drop_off_type,
            )
            .join(PatternStop, StopTime.pattern_stop_id == PatternStop.id)
            .where(StopTime.trip_id.in_(trip_ids))
            .order_by(StopTime.trip_id, PatternStop.sequence)
        ).all()

        current_trip = None
        sequence = 0
        for trip_id, _ps_seq, location_id, arrival, departure, timepoint, pickup, drop_off in rows:
            if trip_id != current_trip:
                current_trip = trip_id
                sequence = 0
            sequence += 1
            stop_time_rows.append(
                [
                    trip_id,
                    format_time(arrival),
                    format_time(departure),
                    f"S{location_id}",
                    sequence,
                    BOARDING_CODES.get(pickup, "0"),
                    BOARDING_CODES.get(drop_off, "0"),
                    1 if timepoint else 0,
                ]
            )
    feed.add(
        "stop_times.txt",
        ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence", "pickup_type", "drop_off_type", "timepoint"],
        stop_time_rows,
    )

    # --- transfers.txt -----------------------------------------------------
    # Only the explicit pairs. Stops sharing an area already carry a
    # parent_station, which is how GTFS expresses that relationship -- writing
    # them out again as pairwise transfers would be redundant and would lose
    # the "these are the same place" meaning.
    transfer_rows: list[list] = []
    for row in db.scalars(select(LocationTransfer)).all():
        transfer_rows.append(
            [f"S{row.from_location_id}", f"S{row.to_location_id}", 2, row.walk_seconds]
        )
        if row.is_bidirectional:
            transfer_rows.append(
                [f"S{row.to_location_id}", f"S{row.from_location_id}", 2, row.walk_seconds]
            )
    feed.add(
        "transfers.txt",
        ["from_stop_id", "to_stop_id", "transfer_type", "min_transfer_time"],
        transfer_rows,
    )

    # --- fare_attributes.txt / fare_rules.txt ------------------------------
    # Each origin/destination zone pair becomes its own fare, which is how
    # GTFS models a zonal matrix.
    zones = {z.id: z for z in db.scalars(select(FareZone)).all()}
    fare_rules = db.scalars(select(FareRule)).all()
    feed.add(
        "fare_attributes.txt",
        ["fare_id", "price", "currency_type", "payment_method", "transfers"],
        [
            [f"F{rule.id}", f"{rule.price_cents / 100:.2f}", rule.currency, 0, ""]
            for rule in fare_rules
        ],
    )
    feed.add(
        "fare_rules.txt",
        ["fare_id", "route_id", "origin_id", "destination_id"],
        [
            [f"F{rule.id}", "", rule.origin_zone_id, rule.destination_zone_id]
            for rule in fare_rules
            if rule.origin_zone_id in zones and rule.destination_zone_id in zones
        ],
    )

    # --- feed_info.txt -----------------------------------------------------
    feed.add(
        "feed_info.txt",
        ["feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_start_date", "feed_end_date", "feed_version"],
        [
            [
                agency_name,
                resolve_text(db, "agency_url", "https://example.invalid"),
                resolve_text(db, "agency_lang", "en"),
                _date(board.start_date),
                _date(board.end_date),
                f"{board.name} ({dt.datetime.now():%Y-%m-%d %H:%M})",
            ]
        ],
    )

    filename = f"gtfs_{schedule_version_id}_{_date(board.start_date)}.zip"
    return feed.to_zip(), filename


def validate_feed(db: Session, schedule_version_id: int) -> list[str]:
    """Cheap pre-flight checks: the things that make a reader reject a feed."""
    problems: list[str] = []

    if not resolve_text(db, "agency_url", ""):
        problems.append(
            "agency_url is not set on the Settings page. GTFS requires a URL "
            "on the agency record."
        )
    if not resolve_text(db, "agency_timezone", ""):
        problems.append("agency_timezone is not set; readers cannot interpret stop times.")

    missing_coords = db.scalar(
        select(Location.id)
        .where(Location.location_type == LocationType.STOP.value)
        .where((Location.lat.is_(None)) | (Location.lon.is_(None)))
        .limit(1)
    )
    if missing_coords is not None:
        problems.append(
            "Some stops have no coordinates and will be left out of the feed. "
            "Run the data-quality check on the Locations page."
        )

    calendars = db.scalar(
        select(Calendar.id)
        .where(Calendar.schedule_version_id == schedule_version_id)
        .limit(1)
    )
    if calendars is None:
        problems.append("This board has no calendars, so no service will be exported.")

    trips = db.scalar(
        select(Trip.id).where(Trip.schedule_version_id == schedule_version_id).limit(1)
    )
    if trips is None:
        problems.append("This board has no trips.")

    return problems
