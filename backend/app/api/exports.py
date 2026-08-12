"""Exports: PDF timetables and CSV extracts."""

import csv
import io
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.deps import DbSession, ReaderUser
from app.models import (
    Duty,
    Line,
    Location,
    LocationAttribute,
    Pattern,
    PatternStop,
    ScheduleVersion,
    StopArea,
)
from app.services import duties as duty_service
from app.services import gtfs
from app.services.crud import get_or_404
from app.services.parameters import resolve, resolve_text
from app.services.pdf import render_duty_card_pdf, render_timetable_pdf, safe_filename
from app.services.timetable import build_timetable
from app.timeutil import format_time

router = APIRouter(tags=["exports"])


@router.get(
    "/pdf/timetable",
    summary="Printable timetable for one pattern",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def timetable_pdf(
    db: DbSession,
    _user: ReaderUser,
    schedule_version_id: int,
    pattern_id: Annotated[
        list[int],
        Query(
            description=(
                "Repeat to print several patterns on one sheet, e.g. "
                "?pattern_id=3&pattern_id=4. Their stop lists are merged into "
                "a single column of stops."
            )
        ),
    ],
    calendar_id: int | None = None,
    timepoints_only: bool = Query(
        default=False,
        description=(
            "Print only timepoint stops. Off by default: the full stop list "
            "is printed, with timepoints emphasised in bold."
        ),
    ),
    landscape: bool = True,
):
    timetable = build_timetable(
        db, schedule_version_id, pattern_id, calendar_id, timepoints_only
    )
    board = db.get(ScheduleVersion, schedule_version_id)
    line = db.get(Line, timetable.line_id)

    pdf = render_timetable_pdf(
        timetable,
        board_name=board.name if board else "",
        line_color=line.color if line else None,
        line_text_color=line.text_color if line else None,
        landscape=landscape,
    )
    filename = (
        safe_filename(
            timetable.line_short_name,
            timetable.pattern_name,
            timetable.calendar_name or "",
        )
        + ".pdf"
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get(
    "/pdf/duty-card",
    summary="Printable duty card for one driver's day",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def duty_card_pdf(db: DbSession, _user: ReaderUser, duty_id: int):
    """Sign-on, every piece, breaks and sign-off, with real location names."""
    duty = get_or_404(db, Duty, duty_id, "Duty")
    events = duty_service.expand_for_card(db, duty)
    summary = duty_service.summarise(
        duty_service.resolve_duty(db, duty),
        resolve(db, "min_single_break_minutes") or 0,
    )
    issues = duty_service.validate_duty(db, duty)
    board = db.get(ScheduleVersion, duty.schedule_version_id)
    instance_name = resolve_text(db, "instance_name", "Transit")

    pdf = render_duty_card_pdf(
        duty=duty,
        events=events,
        summary=summary,
        issues=issues,
        driver_name=duty.driver.display_name if duty.driver else None,
        driver_code=duty.driver.code if duty.driver else None,
        board_name=board.name if board else "",
        agency_name=resolve_text(db, "agency_name", instance_name),
    )
    filename = safe_filename("duty", duty.name, str(duty.date)) + ".pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get(
    "/gtfs/validate",
    summary="Pre-flight checks before exporting a GTFS feed",
    response_model=list[str],
)
def gtfs_validate(db: DbSession, _user: ReaderUser, schedule_version_id: int):
    """The things that would make a GTFS reader reject the feed."""
    return gtfs.validate_feed(db, schedule_version_id)


@router.get(
    "/gtfs/export",
    summary="GTFS feed for one schedule board",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
def gtfs_export(db: DbSession, _user: ReaderUser, schedule_version_id: int):
    """A standards-compliant feed, ready for a journey planner or passenger app.

    Only passenger-facing data is included: depots, garages, layover points,
    blocks-as-operations and duties stay internal.
    """
    try:
        payload, filename = gtfs.export_feed(db, schedule_version_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


#: Excel reads a UTF-8 CSV as the local codepage unless it sees a BOM, which
#: turns every accented stop name into mojibake. Written as an escape rather
#: than a literal so it survives any editor round-trip.
UTF8_BOM = "\ufeff"


def _csv_response(rows: list[list], header: list[str], filename: str) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    # BOM so Excel opens UTF-8 stop names correctly instead of mojibake.
    return Response(
        content=UTF8_BOM + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/csv/locations", summary="Locations as CSV", response_class=Response)
def locations_csv(db: DbSession, _user: ReaderUser):
    locations = db.scalars(select(Location).order_by(Location.name)).all()
    areas = {
        area_id: name
        for area_id, name in db.execute(select(StopArea.id, StopArea.name)).all()
    }
    attributes: dict[int, dict[str, str | None]] = {}
    for row in db.scalars(select(LocationAttribute)).all():
        attributes.setdefault(row.location_id, {})[row.attribute_key] = row.attribute_value

    # One column per attribute key actually in use, so the export stays
    # readable as keys are added and removed.
    keys = sorted({key for values in attributes.values() for key in values})

    header = [
        "id", "name", "code", "location_type", "lat", "lon",
        "zone_id", "area", "is_active",
    ] + keys
    rows = [
        [
            loc.id, loc.name, loc.code or "", loc.location_type,
            loc.lat if loc.lat is not None else "",
            loc.lon if loc.lon is not None else "",
            loc.zone_id or "", areas.get(loc.area_id, ""), loc.is_active,
        ]
        + [attributes.get(loc.id, {}).get(key, "") or "" for key in keys]
        for loc in locations
    ]
    return _csv_response(rows, header, "locations.csv")


@router.get("/csv/stop-times", summary="Stop times for a board as CSV", response_class=Response)
def stop_times_csv(db: DbSession, _user: ReaderUser, schedule_version_id: int):
    """Flat trip x stop extract -- the format most downstream tools want."""
    from app.models import StopTime, Trip

    rows = db.execute(
        select(
            Trip.id,
            Line.short_name,
            Pattern.name,
            Pattern.direction,
            Trip.headsign,
            PatternStop.sequence,
            Location.name,
            Location.code,
            StopTime.arrival_seconds,
            StopTime.departure_seconds,
            StopTime.is_timepoint,
        )
        .join(Pattern, Trip.pattern_id == Pattern.id)
        .join(Line, Pattern.line_id == Line.id)
        .join(StopTime, StopTime.trip_id == Trip.id)
        .join(PatternStop, StopTime.pattern_stop_id == PatternStop.id)
        .join(Location, PatternStop.location_id == Location.id)
        .where(Trip.schedule_version_id == schedule_version_id)
        .order_by(Line.short_name, Trip.id, PatternStop.sequence)
    ).all()

    header = [
        "trip_id", "line", "pattern", "direction", "headsign", "stop_sequence",
        "stop_name", "stop_code", "arrival", "departure", "timepoint",
    ]
    data = [
        [
            trip_id, short_name, pattern_name, direction, headsign or "",
            sequence, stop_name, stop_code or "",
            format_time(arrival), format_time(departure), timepoint,
        ]
        for (
            trip_id, short_name, pattern_name, direction, headsign, sequence,
            stop_name, stop_code, arrival, departure, timepoint,
        ) in rows
    ]
    return _csv_response(data, header, f"stop_times_board_{schedule_version_id}.csv")


routers: list[APIRouter] = [router]
