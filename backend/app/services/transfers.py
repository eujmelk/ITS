"""The walking-transfer graph.

Exactly two sources feed it, and nothing else -- in particular, proximity in
lat/lon never creates an edge. A highway or a river can sit between two
coordinates that look adjacent on a map, so connectivity is always something
a planner has stated explicitly.

  1. ``stop_areas``      -- every ordered pair of stop-type locations sharing
                            an ``area_id``, at the area's default cross time.
  2. ``location_transfers`` -- explicit pairwise rows, which take precedence
                            over an area default for the same pair.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import LocationType
from app.models import Location, LocationTransfer, StopArea
from app.schemas.locations import TransferEdge

AREA_SOURCE = "stop_area"
EXPLICIT_SOURCE = "explicit"


def build_edges(db: Session) -> list[TransferEdge]:
    edges: dict[tuple[int, int], TransferEdge] = {}

    # (1) Stop areas: membership is flagged once per location, so adding a
    # third stop on the same corner needs no new pairwise rows.
    area_rows = db.execute(
        select(Location.area_id, Location.id)
        .where(Location.area_id.is_not(None))
        .where(Location.location_type == LocationType.STOP.value)
        .where(Location.is_active.is_(True))
        .order_by(Location.area_id, Location.id)
    ).all()

    members: dict[int, list[int]] = defaultdict(list)
    for area_id, location_id in area_rows:
        members[area_id].append(location_id)

    if members:
        cross_times = {
            area_id: seconds
            for area_id, seconds in db.execute(
                select(StopArea.id, StopArea.default_transfer_seconds).where(
                    StopArea.id.in_(members.keys())
                )
            ).all()
        }
        for area_id, location_ids in members.items():
            seconds = cross_times.get(area_id, 120)
            for origin in location_ids:
                for destination in location_ids:
                    if origin == destination:
                        continue
                    edges[(origin, destination)] = TransferEdge(
                        from_location_id=origin,
                        to_location_id=destination,
                        walk_seconds=seconds,
                        source=AREA_SOURCE,
                    )

    # (2) Explicit pairs. A specific walk time is a deliberate statement, so
    # it overwrites whatever the area default produced for that pair.
    for row in db.scalars(select(LocationTransfer)).all():
        edges[(row.from_location_id, row.to_location_id)] = TransferEdge(
            from_location_id=row.from_location_id,
            to_location_id=row.to_location_id,
            walk_seconds=row.walk_seconds,
            source=EXPLICIT_SOURCE,
        )
        if row.is_bidirectional:
            edges[(row.to_location_id, row.from_location_id)] = TransferEdge(
                from_location_id=row.to_location_id,
                to_location_id=row.from_location_id,
                walk_seconds=row.walk_seconds,
                source=EXPLICIT_SOURCE,
            )

    _label(db, edges.values())
    return sorted(
        edges.values(), key=lambda e: (e.from_location_name or "", e.to_location_name or "")
    )


def _label(db: Session, edges) -> None:
    """Fill in endpoint names, one query for the whole set."""
    ids = {e.from_location_id for e in edges} | {e.to_location_id for e in edges}
    if not ids:
        return
    names = {
        location_id: name
        for location_id, name in db.execute(
            select(Location.id, Location.name).where(Location.id.in_(ids))
        ).all()
    }
    for edge in edges:
        edge.from_location_name = names.get(edge.from_location_id)
        edge.to_location_name = names.get(edge.to_location_id)


def build_adjacency(db: Session) -> dict[int, list[TransferEdge]]:
    """Edges grouped by origin, ready for the itinerary search."""
    adjacency: dict[int, list[TransferEdge]] = defaultdict(list)
    for edge in build_edges(db):
        adjacency[edge.from_location_id].append(edge)
    return dict(adjacency)


def edges_for_location(db: Session, location_id: int) -> list[TransferEdge]:
    return [e for e in build_edges(db) if e.from_location_id == location_id]
