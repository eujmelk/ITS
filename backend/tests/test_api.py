"""End-to-end walk through the phases this build covers.

Ordered deliberately: later tests depend on ids created by earlier ones, which
mirrors how the application is actually used (you cannot build a block before
there are trips to put in it).
"""

import datetime as dt

from app.config import settings

API = settings.api_prefix

state: dict = {}


def test_health_and_config_are_public(client):
    assert client.get(f"{API}/health").json()["status"] == "ok"
    config = client.get(f"{API}/config").json()
    assert "map_tile_url" in config


def test_unauthenticated_requests_are_rejected(client):
    assert client.get(f"{API}/locations").status_code == 401


def test_bad_password_is_rejected(client):
    response = client.post(
        f"{API}/auth/login", data={"username": "admin", "password": "wrong"}
    )
    assert response.status_code == 401


def test_parameters_were_seeded(client, auth):
    values = client.get(f"{API}/parameters/effective", headers=auth).json()
    assert values["min_break_minutes"] == 45
    assert values["max_driving_minutes_per_day"] == 540
    # bool parameters must come back as real booleans, not the string "false"
    assert values["require_break_at_driver_changeover"] is False


def test_create_zones_and_locations(client, auth):
    zone = client.post(
        f"{API}/fare-zones", json={"name": "Zone A", "code": "A"}, headers=auth
    )
    assert zone.status_code == 201, zone.text
    state["zone_a"] = zone.json()["id"]

    zone_b = client.post(
        f"{API}/fare-zones", json={"name": "Zone B", "code": "B"}, headers=auth
    )
    state["zone_b"] = zone_b.json()["id"]

    depot = client.post(
        f"{API}/locations",
        json={"name": "Test Depot", "code": "DEP", "location_type": "depot",
              "lat": 52.39, "lon": 4.89},
        headers=auth,
    )
    assert depot.status_code == 201, depot.text
    state["depot"] = depot.json()["id"]

    state["stops"] = []
    for index, name in enumerate(["Alpha", "Bravo", "Charlie"]):
        response = client.post(
            f"{API}/locations",
            json={
                "name": name,
                "code": f"S{index}",
                "location_type": "stop",
                "lat": 52.37 + index * 0.01,
                "lon": 4.89,
                "zone_id": state["zone_a"],
                "attributes": [{"attribute_key": "has_shelter", "attribute_value": "true"}],
            },
            headers=auth,
        )
        assert response.status_code == 201, response.text
        state["stops"].append(response.json()["id"])

    detail = client.get(f"{API}/locations/{state['stops'][0]}", headers=auth).json()
    assert detail["zone_name"] == "Zone A"
    assert detail["attributes"][0]["attribute_key"] == "has_shelter"


def test_generic_attributes_can_be_replaced_without_a_schema_change(client, auth):
    location_id = state["stops"][0]
    response = client.patch(
        f"{API}/locations/{location_id}",
        json={
            "attributes": [
                {"attribute_key": "has_bench", "attribute_value": "true"},
                {"attribute_key": "some_brand_new_idea", "attribute_value": "42"},
            ]
        },
        headers=auth,
    )
    assert response.status_code == 200, response.text
    keys = {a["attribute_key"] for a in response.json()["attributes"]}
    assert keys == {"has_bench", "some_brand_new_idea"}


def test_stop_area_membership_creates_transfer_edges(client, auth):
    area = client.post(
        f"{API}/stop-areas",
        json={"name": "Test Corner", "default_transfer_seconds": 150},
        headers=auth,
    )
    assert area.status_code == 201, area.text
    state["area"] = area.json()["id"]

    members = client.put(
        f"{API}/stop-areas/{state['area']}/members",
        json={"location_ids": state["stops"][:2]},
        headers=auth,
    )
    assert members.status_code == 200, members.text
    assert len(members.json()["location_ids"]) == 2

    edges = client.get(f"{API}/location-transfers/graph/edges", headers=auth).json()
    pairs = {(e["from_location_id"], e["to_location_id"]): e for e in edges}
    # Membership is flagged per stop, but the edge exists in both directions.
    assert (state["stops"][0], state["stops"][1]) in pairs
    assert (state["stops"][1], state["stops"][0]) in pairs
    edge = pairs[(state["stops"][0], state["stops"][1])]
    assert edge["walk_seconds"] == 150
    assert edge["source"] == "stop_area"
    # Names travel with the edge so a client need not hold the whole table.
    assert edge["from_location_name"] == "Alpha"
    assert edge["to_location_name"] == "Bravo"


def test_depot_cannot_join_a_stop_area(client, auth):
    response = client.put(
        f"{API}/stop-areas/{state['area']}/members",
        json={"location_ids": [state["depot"]]},
        headers=auth,
    )
    assert response.status_code == 422
    assert "stop" in response.json()["detail"].lower()


def test_explicit_transfer_overrides_the_area_default(client, auth):
    response = client.post(
        f"{API}/location-transfers",
        json={
            "from_location_id": state["stops"][0],
            "to_location_id": state["stops"][1],
            "walk_seconds": 400,
            "is_bidirectional": True,
        },
        headers=auth,
    )
    assert response.status_code == 201, response.text

    edges = client.get(f"{API}/location-transfers/graph/edges", headers=auth).json()
    edge = next(
        e
        for e in edges
        if e["from_location_id"] == state["stops"][0]
        and e["to_location_id"] == state["stops"][1]
    )
    assert edge["walk_seconds"] == 400
    assert edge["source"] == "explicit"


def test_transfers_are_never_inferred_from_proximity(client, auth):
    """Charlie is metres from the others but in no area and no transfer row."""
    edges = client.get(f"{API}/location-transfers/graph/edges", headers=auth).json()
    involved = {e["from_location_id"] for e in edges} | {e["to_location_id"] for e in edges}
    assert state["stops"][2] not in involved


def test_create_line_and_pattern(client, auth):
    line = client.post(
        f"{API}/lines",
        json={
            "short_name": "T1",
            "long_name": "Test line",
            "mode": "bus",
            "attributes": [{"attribute_key": "night_service", "attribute_value": "false"}],
        },
        headers=auth,
    )
    assert line.status_code == 201, line.text
    state["line"] = line.json()["id"]
    assert line.json()["attributes"][0]["attribute_key"] == "night_service"

    pattern = client.post(
        f"{API}/patterns",
        json={"line_id": state["line"], "name": "Outbound", "direction": 0,
              "headsign": "Charlie"},
        headers=auth,
    )
    assert pattern.status_code == 201, pattern.text
    state["pattern"] = pattern.json()["id"]

    stops = client.put(
        f"{API}/patterns/{state['pattern']}/stops",
        json={
            "stops": [
                {"location_id": state["stops"][0], "sequence": 1, "is_timepoint": True,
                 "default_run_seconds": 0, "default_dwell_seconds": 30},
                {"location_id": state["stops"][1], "sequence": 2,
                 "default_run_seconds": 300, "default_dwell_seconds": 0},
                {"location_id": state["stops"][2], "sequence": 3, "is_timepoint": True,
                 "default_run_seconds": 240, "default_dwell_seconds": 0},
            ]
        },
        headers=auth,
    )
    assert stops.status_code == 200, stops.text
    assert stops.json()["stop_count"] == 3
    state["pattern_stops"] = [s["id"] for s in stops.json()["stops"]]


def test_pattern_cannot_call_at_a_depot(client, auth):
    """Enforced in the service layer so it reads as a validation error."""
    pattern = client.post(
        f"{API}/patterns",
        json={"line_id": state["line"], "name": "Bad", "direction": 1},
        headers=auth,
    ).json()
    response = client.put(
        f"{API}/patterns/{pattern['id']}/stops",
        json={"stops": [{"location_id": state["depot"], "sequence": 1}]},
        headers=auth,
    )
    assert response.status_code == 422
    assert "depot" in response.json()["detail"].lower()


def test_board_and_calendar(client, auth):
    today = dt.date.today()
    board = client.post(
        f"{API}/schedule-versions",
        json={
            "name": "Test board",
            "start_date": today.isoformat(),
            "end_date": (today + dt.timedelta(days=90)).isoformat(),
            "status": "active",
        },
        headers=auth,
    )
    assert board.status_code == 201, board.text
    state["board"] = board.json()["id"]

    calendar = client.post(
        f"{API}/calendars",
        json={
            "schedule_version_id": state["board"],
            "name": "Weekdays",
            "monday": True, "tuesday": True, "wednesday": True,
            "thursday": True, "friday": True,
        },
        headers=auth,
    )
    assert calendar.status_code == 201, calendar.text
    state["calendar"] = calendar.json()["id"]


def test_board_rejects_reversed_dates(client, auth):
    response = client.post(
        f"{API}/schedule-versions",
        json={"name": "Backwards", "start_date": "2026-06-01", "end_date": "2026-01-01"},
        headers=auth,
    )
    assert response.status_code == 422


def test_generate_trips_at_a_headway(client, auth):
    response = client.post(
        f"{API}/trips/generate",
        json={
            "schedule_version_id": state["board"],
            "pattern_id": state["pattern"],
            "calendar_id": state["calendar"],
            "first_departure": "06:00",
            "last_departure": "07:00",
            "headway_minutes": 30,
        },
        headers=auth,
    )
    assert response.status_code == 201, response.text
    assert response.json()["count"] == 3
    state["trips"] = response.json()["created_trip_ids"]

    detail = client.get(f"{API}/trips/{state['trips'][0]}/detail", headers=auth).json()
    # 06:00 + 30s dwell, then 300s to Bravo, then 240s to Charlie.
    assert detail["stop_times"][0]["departure_seconds"] == "06:00:30"
    assert detail["stop_times"][1]["arrival_seconds"] == "06:05:30"
    assert detail["stop_times"][2]["arrival_seconds"] == "06:09:30"
    assert detail["start_seconds"] == "06:00:30"


def test_trip_shift_preserves_running_times(client, auth):
    trip_id = state["trips"][2]
    before = client.get(f"{API}/trips/{trip_id}/detail", headers=auth).json()
    response = client.patch(f"{API}/trips/{trip_id}", json={"shift_seconds": 600}, headers=auth)
    assert response.status_code == 200, response.text
    after = response.json()

    def spans(trip):
        times = [t["arrival_seconds"] for t in trip["stop_times"]]
        return times

    assert spans(after) != spans(before)
    assert after["stop_times"][0]["departure_seconds"] == "07:10:30"
    # Shifted, not stretched.
    assert after["stop_times"][2]["arrival_seconds"] == "07:19:30"


def test_timetable_grid(client, auth):
    grid = client.get(
        f"{API}/timetables",
        params={"schedule_version_id": state["board"], "pattern_id": state["pattern"]},
        headers=auth,
    ).json()
    assert len(grid["rows"]) == 3
    assert len(grid["trip_ids"]) == 3
    assert grid["total_trips"] == 3
    # Columns are ordered by departure, so the shifted trip is still last.
    assert grid["rows"][0]["cells"][0]["departure_seconds"] == "06:00:30"
    assert grid["rows"][0]["cells"][2]["departure_seconds"] == "07:10:30"


def test_timetable_columns_page_without_losing_the_ordering(client, auth):
    """Ordering by departure happens before the slice, not after it."""
    base = {"schedule_version_id": state["board"], "pattern_id": state["pattern"]}
    first = client.get(
        f"{API}/timetables", params={**base, "limit": 2, "offset": 0}, headers=auth
    ).json()
    second = client.get(
        f"{API}/timetables", params={**base, "limit": 2, "offset": 2}, headers=auth
    ).json()

    assert first["total_trips"] == 3
    assert len(first["trip_ids"]) == 2
    assert len(second["trip_ids"]) == 1
    assert not set(first["trip_ids"]) & set(second["trip_ids"])
    # Earliest two on page one, the shifted 07:10 trip alone on page two.
    assert first["rows"][0]["cells"][0]["departure_seconds"] == "06:00:30"
    assert second["rows"][0]["cells"][0]["departure_seconds"] == "07:10:30"


def test_fare_matrix_and_quote(client, auth):
    filled = client.post(
        f"{API}/fares/matrix/fill",
        params={"price_cents": 250, "currency": "EUR"},
        headers=auth,
    )
    assert filled.status_code == 200, filled.text
    assert filled.json()["missing_count"] == 0
    # Two zones -> a 2x2 matrix, diagonal included.
    assert len(filled.json()["cells"]) == 4

    quote = client.get(
        f"{API}/fares/quote",
        params={
            "from_location_id": state["stops"][0],
            "to_location_id": state["stops"][1],
        },
        headers=auth,
    ).json()
    assert quote["matched"] is True
    assert quote["price_cents"] == 250


def test_fare_quote_without_a_zone_explains_itself(client, auth):
    quote = client.get(
        f"{API}/fares/quote",
        params={"from_location_id": state["depot"], "to_location_id": state["stops"][0]},
        headers=auth,
    ).json()
    assert quote["matched"] is False
    assert "fare zone" in quote["reason"]


def test_block_pieces_resolve_endpoints_from_trips(client, auth):
    block = client.post(
        f"{API}/blocks",
        json={"schedule_version_id": state["board"], "name": "B01"},
        headers=auth,
    )
    assert block.status_code == 201, block.text
    state["block"] = block.json()["id"]

    response = client.put(
        f"{API}/blocks/{state['block']}/pieces",
        json={
            "pieces": [
                {
                    "sequence": 1, "piece_type": "pull_out",
                    "from_location_id": state["depot"],
                    "to_location_id": state["stops"][0],
                    "start_seconds": "05:45", "end_seconds": "06:00",
                },
                {"sequence": 2, "piece_type": "trip", "trip_id": state["trips"][0]},
            ]
        },
        headers=auth,
    )
    assert response.status_code == 200, response.text
    pieces = response.json()["pieces"]

    # The trip piece carries no times of its own; they come from stop_times.
    assert pieces[1]["start_seconds"] is None
    assert pieces[1]["effective_start_seconds"] == "06:00:30"
    assert pieces[1]["effective_from_location_id"] == state["stops"][0]
    assert pieces[1]["effective_to_location_id"] == state["stops"][2]


def test_block_validator_reports_a_location_break(client, auth):
    """Piece 2 ends at Charlie; piece 3 starts at Alpha with no deadhead."""
    client.put(
        f"{API}/blocks/{state['block']}/pieces",
        json={
            "pieces": [
                {
                    "sequence": 1, "piece_type": "pull_out",
                    "from_location_id": state["depot"],
                    "to_location_id": state["stops"][0],
                    "start_seconds": "05:45", "end_seconds": "06:00",
                },
                {"sequence": 2, "piece_type": "trip", "trip_id": state["trips"][0]},
                {"sequence": 3, "piece_type": "trip", "trip_id": state["trips"][1]},
            ]
        },
        headers=auth,
    )
    report = client.get(f"{API}/blocks/{state['block']}/validate", headers=auth).json()
    codes = [issue["code"] for issue in report["issues"]]
    assert "LOCATION_DISCONTINUITY" in codes
    assert report["ok"] is False
    # Reported, not enforced -- the save above still succeeded.


def test_block_validator_is_happy_once_a_deadhead_is_inserted(client, auth):
    client.put(
        f"{API}/blocks/{state['block']}/pieces",
        json={
            "pieces": [
                {
                    "sequence": 1, "piece_type": "pull_out",
                    "from_location_id": state["depot"],
                    "to_location_id": state["stops"][0],
                    "start_seconds": "05:45", "end_seconds": "06:00",
                },
                {"sequence": 2, "piece_type": "trip", "trip_id": state["trips"][0]},
                {
                    "sequence": 3, "piece_type": "deadhead",
                    "from_location_id": state["stops"][2],
                    "to_location_id": state["stops"][0],
                    "start_seconds": "06:10", "end_seconds": "06:25",
                },
                {"sequence": 4, "piece_type": "trip", "trip_id": state["trips"][1]},
                {
                    "sequence": 5, "piece_type": "pull_in",
                    "from_location_id": state["stops"][2],
                    "to_location_id": state["depot"],
                    "start_seconds": "06:40", "end_seconds": "06:55",
                },
            ]
        },
        headers=auth,
    )
    report = client.get(f"{API}/blocks/{state['block']}/validate", headers=auth).json()
    codes = [issue["code"] for issue in report["issues"]]
    assert "LOCATION_DISCONTINUITY" not in codes
    assert report["ok"] is True


def test_a_trip_cannot_belong_to_two_blocks(client, auth):
    other = client.post(
        f"{API}/blocks",
        json={"schedule_version_id": state["board"], "name": "B02"},
        headers=auth,
    ).json()
    response = client.put(
        f"{API}/blocks/{other['id']}/pieces",
        json={"pieces": [{"sequence": 1, "piece_type": "trip", "trip_id": state["trips"][0]}]},
        headers=auth,
    )
    assert response.status_code == 409


def test_unassigned_trips_excludes_blocked_ones(client, auth):
    page = client.get(
        f"{API}/fleet/unassigned-trips",
        params={"schedule_version_id": state["board"]},
        headers=auth,
    ).json()
    ids = {row["trip_id"] for row in page["items"]}
    assert not {state["trips"][0], state["trips"][1]} & ids
    assert state["trips"][2] in ids
    assert page["total"] == len(page["items"])


def test_unassigned_trips_connects_filter_runs_server_side(client, auth):
    """The shortlist a scheduler wants, computed in the database."""
    connecting = client.get(
        f"{API}/fleet/unassigned-trips",
        params={
            "schedule_version_id": state["board"],
            "connects_from_location_id": state["stops"][0],
        },
        headers=auth,
    ).json()
    # Trip 3 starts at Alpha like the others, so it qualifies.
    assert state["trips"][2] in {r["trip_id"] for r in connecting["items"]}

    elsewhere = client.get(
        f"{API}/fleet/unassigned-trips",
        params={
            "schedule_version_id": state["board"],
            "connects_from_location_id": state["stops"][2],
        },
        headers=auth,
    ).json()
    assert elsewhere["total"] == 0

    # Trip 3 was shifted to 07:10:30, so a later cut-off excludes it.
    late = client.get(
        f"{API}/fleet/unassigned-trips",
        params={"schedule_version_id": state["board"], "not_before": "08:00"},
        headers=auth,
    ).json()
    assert late["total"] == 0


def test_not_before_accepts_a_clock_time_not_just_a_number(client, auth):
    """Regression: the service-day time type works on request bodies, but as a
    query parameter FastAPI rebuilt the field from the base annotation and
    dropped the parser, so "06:09:30" came back as "not a valid integer".
    """
    for value in ("06:09:30", "06:09", "6:09"):
        response = client.get(
            f"{API}/fleet/unassigned-trips",
            params={"schedule_version_id": state["board"], "not_before": value},
            headers=auth,
        )
        assert response.status_code == 200, f"{value}: {response.text}"

    # Connecting trips really are found, which is what the bug hid.
    connecting = client.get(
        f"{API}/fleet/unassigned-trips",
        params={
            "schedule_version_id": state["board"],
            "connects_from_location_id": state["stops"][0],
            "not_before": "06:00:00",
        },
        headers=auth,
    ).json()
    assert connecting["total"] >= 1

    nonsense = client.get(
        f"{API}/fleet/unassigned-trips",
        params={"schedule_version_id": state["board"], "not_before": "half past six"},
        headers=auth,
    )
    assert nonsense.status_code == 422
    assert "not_before" in nonsense.json()["detail"]


def test_listing_reports_the_unpaged_total(client, auth):
    """A truncated page must never look like the whole collection."""
    page = client.get(f"{API}/locations", params={"limit": 2}, headers=auth).json()
    assert len(page["items"]) == 2
    assert page["total"] >= 4  # depot + three stops
    assert page["limit"] == 2

    second = client.get(
        f"{API}/locations", params={"limit": 2, "offset": 2}, headers=auth
    ).json()
    assert {r["id"] for r in page["items"]} & {r["id"] for r in second["items"]} == set()


def test_sorting_is_applied_server_side(client, auth):
    ascending = client.get(
        f"{API}/locations", params={"sort": "name", "order": "asc"}, headers=auth
    ).json()["items"]
    descending = client.get(
        f"{API}/locations", params={"sort": "name", "order": "desc"}, headers=auth
    ).json()["items"]
    names = [r["name"] for r in ascending]
    assert names == sorted(names)
    assert [r["name"] for r in descending] == sorted(names, reverse=True)

    # An unknown column is ignored rather than raising.
    assert (
        client.get(f"{API}/locations", params={"sort": "nonsense"}, headers=auth).status_code
        == 200
    )


def test_a_deadhead_piece_needs_its_endpoints(client, auth):
    response = client.put(
        f"{API}/blocks/{state['block']}/pieces",
        json={"pieces": [{"sequence": 1, "piece_type": "deadhead"}]},
        headers=auth,
    )
    assert response.status_code == 422


def test_timetable_prints_every_stop_by_default(client, auth):
    """Bravo is not a timepoint, but it must still appear on the printed sheet.

    The grid the PDF is built from is the same one the UI shows, so this
    covers both.
    """
    base = {"schedule_version_id": state["board"], "pattern_id": state["pattern"]}

    full = client.get(f"{API}/timetables", params=base, headers=auth).json()
    assert [r["location_name"] for r in full["rows"]] == ["Alpha", "Bravo", "Charlie"]
    assert [r["is_timepoint"] for r in full["rows"]] == [True, False, True]

    # The old behaviour is still available, and still keeps the termini.
    condensed = client.get(
        f"{API}/timetables", params={**base, "timepoints_only": True}, headers=auth
    ).json()
    assert [r["location_name"] for r in condensed["rows"]] == ["Alpha", "Charlie"]


def test_pdf_timetable_renders(client, auth):
    response = client.get(
        f"{API}/pdf/timetable",
        params={"schedule_version_id": state["board"], "pattern_id": state["pattern"]},
        headers=auth,
    )
    assert response.status_code == 200, response.text[:400]
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"


def test_csv_export(client, auth):
    response = client.get(
        f"{API}/csv/stop-times",
        params={"schedule_version_id": state["board"]},
        headers=auth,
    )
    assert response.status_code == 200
    assert "trip_id,line,pattern" in response.text


def test_drivers_are_live(client, auth):
    response = client.post(
        f"{API}/drivers",
        json={"code": "D001", "first_name": "Alex", "last_name": "Moreau",
              "base_location_id": state["depot"]},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    assert response.json()["display_name"] == "Alex Moreau"
    assert response.json()["base_location_name"] == "Test Depot"


def test_viewer_cannot_write(client, auth):
    created = client.post(
        f"{API}/users",
        json={"username": "viewer1", "password": "viewer-password", "role": "viewer"},
        headers=auth,
    )
    assert created.status_code == 201, created.text

    token = client.post(
        f"{API}/auth/login",
        data={"username": "viewer1", "password": "viewer-password"},
    ).json()["access_token"]
    viewer = {"Authorization": f"Bearer {token}"}

    assert client.get(f"{API}/locations", headers=viewer).status_code == 200
    blocked = client.post(
        f"{API}/locations", json={"name": "Nope", "location_type": "stop"}, headers=viewer
    )
    assert blocked.status_code == 403
    # Parameters are admin-only, even for a planner.
    assert (
        client.patch(f"{API}/parameters/min_break_minutes", json={"value": "10"}, headers=viewer).status_code
        == 403
    )


def test_admin_cannot_lock_themselves_out(client, auth):
    me = client.get(f"{API}/auth/me", headers=auth).json()
    response = client.patch(f"{API}/users/{me['id']}", json={"is_active": False}, headers=auth)
    assert response.status_code == 400


def test_deleting_a_location_used_by_a_pattern_is_refused(client, auth):
    response = client.delete(f"{API}/locations/{state['stops'][0]}", headers=auth)
    assert response.status_code == 409
    assert "pattern" in response.json()["detail"].lower()
