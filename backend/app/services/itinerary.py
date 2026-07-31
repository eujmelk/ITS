"""Journey search.

Connection Scan: every trip is chopped into "connections" (a hop from one
stop to the next), the connections are sorted by departure time, and a single
forward pass fixes the earliest reachable time at every stop. It is easy to
verify against a timetable by hand, which matters more here than raw speed --
and one service day is a small enough scan for that trade to be free.

Transfers come from :mod:`app.services.transfers` and nowhere else: stops
sharing a stop area, plus explicit pairwise rows. Coordinate proximity never
creates a connection.
"""

from __future__ import annotations

import datetime as dt
from bisect import bisect_left
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FareRule, Line, Location, Pattern, PatternStop, StopTime, Trip
from app.schemas.itinerary import Itinerary, ItineraryLeg, ItineraryRequest
from app.services import transfers as transfer_service
from app.services.calendars import active_calendar_ids
from app.timeutil import MAX_SERVICE_SECONDS


@dataclass(frozen=True)
class Connection:
    trip_id: int
    from_location_id: int
    to_location_id: int
    departure: int
    arrival: int
    sequence: int


@dataclass
class TripInfo:
    trip_id: int
    line_id: int | None
    line_short_name: str | None
    headsign: str | None


@dataclass
class Label:
    """How we got to a stop, for reconstructing the journey afterwards."""

    arrival: int
    kind: str  # 'ride' | 'walk' | 'origin'
    from_location_id: int | None = None
    trip_id: int | None = None
    boarded_at: int | None = None
    departure: int | None = None
    walk_seconds: int | None = None
    transfer_source: str | None = None


def _build_connections(
    db: Session, date: dt.date
) -> tuple[list[Connection], dict[int, TripInfo], dict[int, str]]:
    calendar_ids = active_calendar_ids(db, date)
    if not calendar_ids:
        return [], {}, {}

    rows = db.execute(
        select(
            StopTime.trip_id,
            PatternStop.sequence,
            PatternStop.location_id,
            StopTime.arrival_seconds,
            StopTime.departure_seconds,
        )
        .join(Trip, StopTime.trip_id == Trip.id)
        .join(PatternStop, StopTime.pattern_stop_id == PatternStop.id)
        .where(Trip.calendar_id.in_(calendar_ids))
        .order_by(StopTime.trip_id, PatternStop.sequence)
    ).all()

    by_trip: dict[int, list[tuple[int, int, int, int]]] = {}
    for trip_id, sequence, location_id, arrival, departure in rows:
        by_trip.setdefault(trip_id, []).append((sequence, location_id, arrival, departure))

    connections: list[Connection] = []
    for trip_id, calls in by_trip.items():
        calls.sort()
        for (seq_a, loc_a, _arr_a, dep_a), (_seq_b, loc_b, arr_b, _dep_b) in zip(
            calls, calls[1:]
        ):
            # A trip that goes nowhere between two calls is not a connection.
            if loc_a == loc_b:
                continue
            connections.append(
                Connection(
                    trip_id=trip_id,
                    from_location_id=loc_a,
                    to_location_id=loc_b,
                    departure=dep_a,
                    arrival=arr_b,
                    sequence=seq_a,
                )
            )

    connections.sort(key=lambda c: (c.departure, c.arrival))

    trip_info: dict[int, TripInfo] = {}
    if by_trip:
        for trip_id, line_id, short_name, headsign in db.execute(
            select(Trip.id, Line.id, Line.short_name, Trip.headsign)
            .join(Pattern, Trip.pattern_id == Pattern.id)
            .join(Line, Pattern.line_id == Line.id)
            .where(Trip.id.in_(by_trip.keys()))
        ).all():
            trip_info[trip_id] = TripInfo(trip_id, line_id, short_name, headsign)

    location_ids = {c.from_location_id for c in connections} | {
        c.to_location_id for c in connections
    }
    names: dict[int, str] = {}
    if location_ids:
        names = {
            lid: name
            for lid, name in db.execute(
                select(Location.id, Location.name).where(Location.id.in_(location_ids))
            ).all()
        }
    return connections, trip_info, names


def _scan(
    connections: list[Connection],
    footpaths: dict[int, list],
    origin: int,
    depart_after: int,
    min_transfer_seconds: int,
    allow_origin_footpaths: bool = True,
    start_index: int = 0,
) -> dict[int, Label]:
    """One forward pass. Returns the best label for every reachable stop.

    ``allow_origin_footpaths`` exists because earliest-arrival labelling has a
    well-known artifact: walking away from the origin the moment the search
    window opens can reach a neighbouring stop hours before any vehicle does,
    so that stop's label becomes the walk, and every journey through it is
    then reconstructed as "walk, wait an hour, ride" even when boarding at the
    origin would have arrived at exactly the same time. :func:`search` runs
    the scan both ways and keeps the better journey, which removes the
    artifact without needing a full profile search.
    """
    labels: dict[int, Label] = {
        origin: Label(arrival=depart_after, kind="origin")
    }
    # When you may board a *new* trip at a stop: arrival plus the change time.
    # Staying on the same trip is handled by `boarded`, which pays no penalty.
    ready: dict[int, int] = {origin: depart_after}
    boarded: set[int] = set()

    def relax_footpaths(location_id: int, arrival: int) -> None:
        for edge in footpaths.get(location_id, []):
            landed = arrival + edge.walk_seconds
            existing = labels.get(edge.to_location_id)
            if existing is None or landed < existing.arrival:
                labels[edge.to_location_id] = Label(
                    arrival=landed,
                    kind="walk",
                    from_location_id=location_id,
                    walk_seconds=edge.walk_seconds,
                    departure=arrival,
                    transfer_source=edge.source,
                )
                # A walk already includes the changing time.
                ready[edge.to_location_id] = landed

    if allow_origin_footpaths:
        relax_footpaths(origin, depart_after)

    # `start_index` is the first connection departing at or after
    # `depart_after`; later rounds of the search skip the whole morning
    # instead of walking past it.
    for connection in connections[start_index:]:
        if connection.departure < depart_after:
            continue
        on_board = connection.trip_id in boarded
        if not on_board:
            available = ready.get(connection.from_location_id)
            if available is None or available > connection.departure:
                continue
            boarded.add(connection.trip_id)

        existing = labels.get(connection.to_location_id)
        if existing is not None and existing.arrival <= connection.arrival:
            continue

        labels[connection.to_location_id] = Label(
            arrival=connection.arrival,
            kind="ride",
            from_location_id=connection.from_location_id,
            trip_id=connection.trip_id,
            departure=connection.departure,
        )
        candidate_ready = connection.arrival + min_transfer_seconds
        if candidate_ready < ready.get(connection.to_location_id, MAX_SERVICE_SECONDS + 1):
            ready[connection.to_location_id] = candidate_ready
        relax_footpaths(connection.to_location_id, connection.arrival)

    return labels


def _reconstruct(
    labels: dict[int, Label],
    origin: int,
    destination: int,
    trip_info: dict[int, TripInfo],
    names: dict[int, str],
) -> list[ItineraryLeg] | None:
    """Walk the back-pointers, merging consecutive hops on the same trip."""
    if destination not in labels:
        return None

    chain: list[tuple[int, Label]] = []
    cursor = destination
    guard = 0
    while cursor != origin:
        label = labels.get(cursor)
        if label is None or label.from_location_id is None:
            return None
        chain.append((cursor, label))
        cursor = label.from_location_id
        guard += 1
        if guard > 500:
            return None
    chain.reverse()

    legs: list[ItineraryLeg] = []
    for stop_id, label in chain:
        start = label.from_location_id or origin
        if label.kind == "walk":
            legs.append(
                ItineraryLeg(
                    kind="walk",
                    from_location_id=start,
                    from_location_name=names.get(start, str(start)),
                    to_location_id=stop_id,
                    to_location_name=names.get(stop_id, str(stop_id)),
                    depart_seconds=label.departure,
                    arrive_seconds=label.arrival,
                    duration_seconds=label.walk_seconds or 0,
                    transfer_source=label.transfer_source,
                )
            )
            continue

        info = trip_info.get(label.trip_id or -1)
        previous = legs[-1] if legs else None
        if (
            previous is not None
            and previous.kind == "ride"
            and previous.trip_id == label.trip_id
            and previous.to_location_id == start
        ):
            # Same vehicle, next stop: extend rather than start a new leg.
            previous.to_location_id = stop_id
            previous.to_location_name = names.get(stop_id, str(stop_id))
            previous.arrive_seconds = label.arrival
            previous.duration_seconds = (previous.arrive_seconds or 0) - (
                previous.depart_seconds or 0
            )
            previous.intermediate_stop_count += 1
            continue

        legs.append(
            ItineraryLeg(
                kind="ride",
                from_location_id=start,
                from_location_name=names.get(start, str(start)),
                to_location_id=stop_id,
                to_location_name=names.get(stop_id, str(stop_id)),
                depart_seconds=label.departure,
                arrive_seconds=label.arrival,
                duration_seconds=(label.arrival or 0) - (label.departure or 0),
                trip_id=label.trip_id,
                line_id=info.line_id if info else None,
                line_short_name=info.line_short_name if info else None,
                headsign=info.headsign if info else None,
            )
        )

    _schedule_walks_late(legs)
    return legs


def _schedule_walks_late(legs: list[ItineraryLeg]) -> None:
    """Push each walk as late as it can go.

    The scan times a walk from the moment you *could* start it, which makes a
    journey look like it begins with a stroll and a long wait at the stop. A
    walk is elastic -- what matters is arriving before the vehicle leaves --
    so each one is slid forward to finish exactly when the next leg departs.
    Trailing walks keep their original timing; there is nothing to wait for.
    """
    for index in range(len(legs) - 1, -1, -1):
        leg = legs[index]
        if leg.kind != "walk" or index == len(legs) - 1:
            continue
        next_departure = legs[index + 1].depart_seconds
        if next_departure is None:
            continue
        leg.arrive_seconds = next_departure
        leg.depart_seconds = next_departure - leg.duration_seconds


def _price(db: Session, origin: int, destination: int) -> tuple[int | None, str | None]:
    zones = {
        lid: zone_id
        for lid, zone_id in db.execute(
            select(Location.id, Location.zone_id).where(
                Location.id.in_([origin, destination])
            )
        ).all()
    }
    origin_zone, destination_zone = zones.get(origin), zones.get(destination)
    if origin_zone is None or destination_zone is None:
        return None, None
    rule = db.scalar(
        select(FareRule)
        .where(FareRule.origin_zone_id == origin_zone)
        .where(FareRule.destination_zone_id == destination_zone)
    )
    return (rule.price_cents, rule.currency) if rule else (None, None)


def search(db: Session, request: ItineraryRequest) -> list[Itinerary]:
    """Earliest-arrival journeys, then successively later departures.

    Re-running the scan from just after each result's first departure gives a
    spread of genuinely different options rather than N variations on one.
    """
    if request.from_location_id == request.to_location_id:
        return []

    connections, trip_info, names = _build_connections(db, request.date)
    if not connections:
        return []

    footpaths = transfer_service.build_adjacency(db)
    depart_after = request.depart_after if request.depart_after is not None else 0
    departures = [c.departure for c in connections]

    # The second scan only differs when the origin has somewhere to walk to,
    # so for the great majority of stops it is skipped outright.
    origin_variants = (
        (False, True) if footpaths.get(request.from_location_id) else (False,)
    )

    results: list[Itinerary] = []
    seen: set[tuple] = set()

    for _ in range(request.max_results + 2):
        if len(results) >= request.max_results:
            break

        start_index = bisect_left(departures, depart_after)
        if start_index >= len(connections):
            break

        # Both variants of the scan, keeping whichever journey is better.
        # See _scan's docstring: allowing a walk away from the origin at the
        # start of the window can tie on arrival while adding a pointless leg.
        candidates: list[list[ItineraryLeg]] = []
        for allow_origin_walk in origin_variants:
            labels = _scan(
                connections,
                footpaths,
                request.from_location_id,
                depart_after,
                request.min_transfer_seconds,
                allow_origin_footpaths=allow_origin_walk,
                start_index=start_index,
            )
            found = _reconstruct(
                labels,
                request.from_location_id,
                request.to_location_id,
                trip_info,
                names,
            )
            if found:
                candidates.append(found)

        if not candidates:
            break

        # Earliest arrival first; on a tie, the journey with fewer legs.
        legs = min(
            candidates,
            key=lambda option: (option[-1].arrive_seconds or 0, len(option)),
        )

        ride_legs = [leg for leg in legs if leg.kind == "ride"]
        transfers = max(0, len(ride_legs) - 1)
        first_departure = next(
            (leg.depart_seconds for leg in legs if leg.depart_seconds is not None), None
        )
        arrival = legs[-1].arrive_seconds

        if arrival is None or first_departure is None:
            break
        if request.arrive_before is not None and arrival > request.arrive_before:
            break

        signature = tuple(
            (leg.kind, leg.trip_id, leg.from_location_id, leg.to_location_id) for leg in legs
        )
        if signature not in seen and transfers <= request.max_transfers:
            seen.add(signature)
            price, currency = _price(
                db, request.from_location_id, request.to_location_id
            )
            results.append(
                Itinerary(
                    depart_seconds=first_departure,
                    arrive_seconds=arrival,
                    duration_seconds=arrival - first_departure,
                    transfer_count=transfers,
                    legs=legs,
                    fare_price_cents=price,
                    fare_currency=currency,
                )
            )

        # Next round must leave strictly later, or the scan repeats itself.
        depart_after = first_departure + 1
        if depart_after > MAX_SERVICE_SECONDS:
            break

    results.sort(key=lambda i: (i.arrive_seconds or 0, i.transfer_count))
    return results[: request.max_results]
