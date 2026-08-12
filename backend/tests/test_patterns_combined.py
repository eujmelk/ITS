"""Pattern attributes and combined multi-pattern timetables.

Runs after test_api.py, which builds the base network: pattern "Outbound"
calls Alpha -> Bravo -> Charlie.
"""

from app.config import settings
from app.services.timetable import merge_stop_orders

from tests.test_api import state

API = settings.api_prefix

combined: dict = {}


# --------------------------------------------------------------------------
# The merge itself -- pure function, worth testing directly.
# --------------------------------------------------------------------------


def test_merge_keeps_the_longest_sequence_as_the_spine():
    stopping = [1, 2, 3, 4, 5]
    express = [1, 3, 5]
    assert merge_stop_orders([express, stopping]) == [1, 2, 3, 4, 5]


def test_merge_inserts_stops_the_spine_does_not_have():
    """Stop 2 exists only on the shorter pattern, and lands between 1 and 5."""
    assert merge_stop_orders([[1, 2, 5], [1, 3, 4, 5]]) == [1, 2, 3, 4, 5]


def test_merge_handles_a_pattern_that_starts_short():
    """A short working that joins the route part-way through."""
    full = [10, 11, 12, 13, 14]
    short = [12, 13, 14]
    assert merge_stop_orders([short, full]) == [10, 11, 12, 13, 14]


def test_merge_of_nothing_is_nothing():
    assert merge_stop_orders([]) == []


# --------------------------------------------------------------------------
# Pattern attributes
# --------------------------------------------------------------------------


def test_lines_have_no_attributes(client, auth):
    """Attributes describe a variant of a service, so they live on patterns.

    Having both levels was ambiguous -- nothing said which won when they
    disagreed -- so the line-level table is gone.
    """
    line = client.get(f"{API}/lines/{state['line']}", headers=auth).json()
    assert "attributes" not in line

    assert client.get(f"{API}/line-attributes", headers=auth).status_code == 404

    # A stray `attributes` key is ignored, not stored somewhere invisible.
    response = client.patch(
        f"{API}/lines/{state['line']}",
        json={"attributes": [{"attribute_key": "TYPE", "attribute_value": "EXP"}]},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert "attributes" not in response.json()


def test_setting_attributes_does_not_500(client, auth):
    """Regression: `apply_updates` matched the SQLAlchemy *relationship* by
    name and assigned a list of plain dicts into it, which SQLAlchemy rejects
    on flush -- surfacing to the user as "Request failed (500)".
    """
    response = client.patch(
        f"{API}/patterns/{state['pattern']}",
        json={"attributes": [{"attribute_key": "via", "attribute_value": "Market"}]},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["badges"] == ["Market"]

    # The same shape on a location, which had the identical latent bug.
    location = client.patch(
        f"{API}/locations/{state['stops'][1]}",
        json={"attributes": [{"attribute_key": "lit", "attribute_value": "true"}]},
        headers=auth,
    )
    assert location.status_code == 200, location.text
    assert location.json()["attributes"][0]["attribute_key"] == "lit"


# --------------------------------------------------------------------------
# GTFS-reserved keys
# --------------------------------------------------------------------------


def test_reserved_keys_are_advertised(client, auth):
    rows = client.get(f"{API}/pattern-attributes/reserved/gtfs", headers=auth).json()
    keys = {row["key"] for row in rows}
    assert keys == {"wheelchair_accessible", "bikes_allowed"}


def test_a_reserved_key_rejects_a_value_gtfs_cannot_express(client, auth):
    response = client.patch(
        f"{API}/patterns/{state['pattern']}",
        json={
            "attributes": [
                {"attribute_key": "wheelchair_accessible", "attribute_value": "maybe"}
            ]
        },
        headers=auth,
    )
    assert response.status_code == 422
    assert "GTFS field" in response.json()["detail"]


def test_reserved_keys_export_into_trips_and_do_not_become_bubbles(client, auth):
    import csv
    import io
    import zipfile

    updated = client.patch(
        f"{API}/patterns/{state['pattern']}",
        json={
            "attributes": [
                {"attribute_key": "TYPE", "attribute_value": "LOCAL"},
                {"attribute_key": "wheelchair_accessible", "attribute_value": "yes"},
                {"attribute_key": "bikes_allowed", "attribute_value": "no"},
            ]
        },
        headers=auth,
    )
    assert updated.status_code == 200, updated.text
    # "yes" beside a line number tells a driver nothing, so reserved keys are
    # exported but not printed as bubbles.
    assert updated.json()["badges"] == ["LOCAL"]

    response = client.get(
        f"{API}/gtfs/export",
        params={"schedule_version_id": state["board"]},
        headers=auth,
    )
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    rows = list(csv.DictReader(io.StringIO(archive.read("trips.txt").decode("utf-8"))))

    trip = next(r for r in rows if r["trip_id"] == str(state["trips"][0]))
    assert trip["wheelchair_accessible"] == "1"  # GTFS: 1 = yes
    assert trip["bikes_allowed"] == "2"  # GTFS: 2 = no


def test_attributes_can_be_set_on_a_pattern(client, auth):
    response = client.patch(
        f"{API}/patterns/{state['pattern']}",
        json={"attributes": [{"attribute_key": "TYPE", "attribute_value": "LOCAL"}]},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["attributes"][0]["attribute_key"] == "TYPE"
    # The *value* is what prints as a bubble, not the key.
    assert body["badges"] == ["LOCAL"]


def test_blank_values_do_not_become_bubbles(client, auth):
    """An attribute used as a flag has nothing to print."""
    response = client.patch(
        f"{API}/patterns/{state['pattern']}",
        json={
            "attributes": [
                {"attribute_key": "TYPE", "attribute_value": "LOCAL"},
                {"attribute_key": "peak_only", "attribute_value": ""},
            ]
        },
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["badges"] == ["LOCAL"]


def test_copying_a_pattern_carries_its_attributes(client, auth):
    """An express pattern's copy is still express until told otherwise."""
    copy = client.post(
        f"{API}/patterns/{state['pattern']}/duplicate",
        params={"name": "Outbound express"},
        headers=auth,
    )
    assert copy.status_code == 201, copy.text
    combined["express"] = copy.json()["id"]
    assert copy.json()["badges"] == ["LOCAL"]

    # Now make it genuinely the express variant.
    updated = client.patch(
        f"{API}/patterns/{combined['express']}",
        json={"attributes": [{"attribute_key": "TYPE", "attribute_value": "EXP"}]},
        headers=auth,
    ).json()
    assert updated["badges"] == ["EXP"]


def test_express_pattern_skips_a_stop(client, auth):
    """Alpha -> Charlie, missing out Bravo."""
    stops = client.get(f"{API}/patterns/{state['pattern']}", headers=auth).json()["stops"]
    alpha, charlie = stops[0], stops[2]

    response = client.put(
        f"{API}/patterns/{combined['express']}/stops",
        json={
            "stops": [
                {
                    "location_id": alpha["location_id"], "sequence": 1,
                    "is_timepoint": True, "default_run_seconds": 0,
                    "default_dwell_seconds": 30,
                },
                {
                    "location_id": charlie["location_id"], "sequence": 2,
                    "is_timepoint": True, "default_run_seconds": 300,
                    "default_dwell_seconds": 0,
                },
            ]
        },
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["stop_count"] == 2

    generated = client.post(
        f"{API}/trips/generate",
        json={
            "schedule_version_id": state["board"],
            "pattern_id": combined["express"],
            "calendar_id": state["calendar"],
            "first_departure": "06:15",
            "last_departure": "06:15",
            "headway_minutes": 30,
        },
        headers=auth,
    )
    assert generated.status_code == 201, generated.text
    combined["express_trip"] = generated.json()["created_trip_ids"][0]


# --------------------------------------------------------------------------
# Combined timetables
# --------------------------------------------------------------------------


def test_a_single_pattern_still_works_unchanged(client, auth):
    grid = client.get(
        f"{API}/timetables",
        params={"schedule_version_id": state["board"], "pattern_id": state["pattern"]},
        headers=auth,
    ).json()
    assert grid["combined"] is False
    assert grid["pattern_ids"] == [state["pattern"]]
    assert [r["location_name"] for r in grid["rows"]] == ["Alpha", "Bravo", "Charlie"]
    assert all(r["partial"] is False for r in grid["rows"])


def test_two_patterns_merge_into_one_column_of_stops(client, auth):
    grid = client.get(
        f"{API}/timetables",
        params=[
            ("schedule_version_id", state["board"]),
            ("pattern_id", state["pattern"]),
            ("pattern_id", combined["express"]),
        ],
        headers=auth,
    ).json()

    assert grid["combined"] is True
    assert len(grid["pattern_names"]) == 2
    # One column of stops, not two lists stapled together.
    assert [r["location_name"] for r in grid["rows"]] == ["Alpha", "Bravo", "Charlie"]

    # Bravo is only served by the stopping pattern.
    bravo = next(r for r in grid["rows"] if r["location_name"] == "Bravo")
    assert bravo["partial"] is True
    alpha = next(r for r in grid["rows"] if r["location_name"] == "Alpha")
    assert alpha["partial"] is False


def test_the_express_column_has_a_gap_at_the_skipped_stop(client, auth):
    grid = client.get(
        f"{API}/timetables",
        params=[
            ("schedule_version_id", state["board"]),
            ("pattern_id", state["pattern"]),
            ("pattern_id", combined["express"]),
        ],
        headers=auth,
    ).json()

    column = grid["trip_ids"].index(combined["express_trip"])
    rows = {r["location_name"]: r for r in grid["rows"]}
    assert rows["Alpha"]["cells"][column]["departure_seconds"] == "06:15:30"
    assert rows["Bravo"]["cells"][column]["departure_seconds"] is None
    assert rows["Charlie"]["cells"][column]["departure_seconds"] == "06:20:30"


def test_columns_report_which_pattern_and_badge_they_carry(client, auth):
    grid = client.get(
        f"{API}/timetables",
        params=[
            ("schedule_version_id", state["board"]),
            ("pattern_id", state["pattern"]),
            ("pattern_id", combined["express"]),
        ],
        headers=auth,
    ).json()

    by_trip = {c["trip_id"]: c for c in grid["columns"]}
    express = by_trip[combined["express_trip"]]
    assert express["pattern_id"] == combined["express"]
    assert express["badges"] == ["EXP"]

    stopping = by_trip[state["trips"][0]]
    assert stopping["badges"] == ["LOCAL"]


def test_combining_patterns_of_different_lines_is_refused(client, auth):
    other_line = client.post(
        f"{API}/lines", json={"short_name": "T9", "mode": "bus"}, headers=auth
    ).json()
    other_pattern = client.post(
        f"{API}/patterns",
        json={"line_id": other_line["id"], "name": "Unrelated", "direction": 0},
        headers=auth,
    ).json()

    response = client.get(
        f"{API}/timetables",
        params=[
            ("schedule_version_id", state["board"]),
            ("pattern_id", state["pattern"]),
            ("pattern_id", other_pattern["id"]),
        ],
        headers=auth,
    )
    assert response.status_code == 422
    assert "same line" in response.json()["detail"]


def test_combined_pdf_renders(client, auth):
    response = client.get(
        f"{API}/pdf/timetable",
        params=[
            ("schedule_version_id", state["board"]),
            ("pattern_id", state["pattern"]),
            ("pattern_id", combined["express"]),
        ],
        headers=auth,
    )
    assert response.status_code == 200, response.text[:400]
    assert response.content[:5] == b"%PDF-"


def test_an_unknown_pattern_is_a_404(client, auth):
    response = client.get(
        f"{API}/timetables",
        params=[
            ("schedule_version_id", state["board"]),
            ("pattern_id", 999999),
        ],
        headers=auth,
    )
    assert response.status_code == 404
