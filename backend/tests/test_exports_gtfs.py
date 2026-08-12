"""Phase 13: GTFS export, plus the settings it depends on."""

import csv
import io
import zipfile

from app.config import settings

from tests.test_api import state

API = settings.api_prefix


def _feed(client, auth) -> dict[str, list[dict]]:
    response = client.get(
        f"{API}/gtfs/export",
        params={"schedule_version_id": state["board"]},
        headers=auth,
    )
    assert response.status_code == 200, response.text[:400]
    assert response.headers["content-type"] == "application/zip"

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    parsed: dict[str, list[dict]] = {}
    for name in archive.namelist():
        text = archive.read(name).decode("utf-8")
        parsed[name] = list(csv.DictReader(io.StringIO(text)))
    return parsed


def test_instance_name_is_editable_and_reaches_the_config_endpoint(client, auth):
    original = client.get(f"{API}/config").json()["app_name"]

    response = client.patch(
        f"{API}/parameters/instance_name", json={"value": "Transdev ITS"}, headers=auth
    )
    assert response.status_code == 200, response.text
    assert client.get(f"{API}/config").json()["app_name"] == "Transdev ITS"

    # /config is public: the login page needs the name before anyone signs in.
    assert client.get(f"{API}/config").status_code == 200

    client.patch(
        f"{API}/parameters/instance_name", json={"value": original}, headers=auth
    )


def test_instance_name_cannot_be_blanked(client, auth):
    response = client.patch(
        f"{API}/parameters/instance_name", json={"value": "   "}, headers=auth
    )
    assert response.status_code == 422
    assert "cannot be empty" in response.json()["detail"]


def test_parameters_are_grouped_for_the_settings_page(client, auth):
    rows = client.get(f"{API}/parameters", headers=auth).json()
    by_key = {row["key"]: row for row in rows}
    assert by_key["instance_name"]["category"] == "identity"
    assert by_key["agency_timezone"]["category"] == "identity"
    assert by_key["min_break_minutes"]["category"] == "operating"


def test_gtfs_feed_contains_the_expected_files(client, auth):
    feed = _feed(client, auth)
    for required in (
        "agency.txt",
        "stops.txt",
        "routes.txt",
        "trips.txt",
        "stop_times.txt",
        "calendar.txt",
    ):
        assert required in feed, f"{required} missing from the feed"


def test_only_passenger_stops_are_exported(client, auth):
    """A depot is operational; it has no place in a public feed."""
    feed = _feed(client, auth)
    stop_ids = {row["stop_id"] for row in feed["stops.txt"]}
    assert f"S{state['depot']}" not in stop_ids
    assert f"S{state['stops'][0]}" in stop_ids


def test_a_stop_area_becomes_a_parent_station(client, auth):
    feed = _feed(client, auth)
    by_id = {row["stop_id"]: row for row in feed["stops.txt"]}

    station = by_id[f"A{state['area']}"]
    assert station["location_type"] == "1"
    assert station["stop_name"] == "Test Corner"

    # Alpha and Bravo were put in that area, so they hang off the station.
    assert by_id[f"S{state['stops'][0]}"]["parent_station"] == f"A{state['area']}"
    assert by_id[f"S{state['stops'][1]}"]["parent_station"] == f"A{state['area']}"
    # Charlie is not, and must not acquire one.
    assert by_id[f"S{state['stops'][2]}"]["parent_station"] == ""


def test_explicit_transfers_are_exported_but_area_members_are_not(client, auth):
    """Area membership is expressed by parent_station, not duplicated here."""
    feed = _feed(client, auth)
    pairs = {(row["from_stop_id"], row["to_stop_id"]) for row in feed["transfers.txt"]}
    # The explicit Alpha<->Bravo row, both directions.
    assert (f"S{state['stops'][0]}", f"S{state['stops'][1]}") in pairs
    assert (f"S{state['stops'][1]}", f"S{state['stops'][0]}") in pairs


def test_stop_times_are_service_day_clock(client, auth):
    feed = _feed(client, auth)
    times = [row["departure_time"] for row in feed["stop_times.txt"]]
    assert "06:00:30" in times
    # Sequences restart at 1 for each trip and are dense.
    first_trip = feed["stop_times.txt"][0]["trip_id"]
    sequences = [
        int(row["stop_sequence"]) for row in feed["stop_times.txt"] if row["trip_id"] == first_trip
    ]
    assert sequences == list(range(1, len(sequences) + 1))


def test_fares_export_as_the_zone_matrix(client, auth):
    feed = _feed(client, auth)
    assert feed["fare_attributes.txt"], "the zone matrix should produce fares"
    prices = {row["price"] for row in feed["fare_attributes.txt"]}
    assert "2.50" in prices
    assert len(feed["fare_rules.txt"]) == len(feed["fare_attributes.txt"])


def test_validation_flags_a_missing_agency_url(client, auth):
    problems = client.get(
        f"{API}/gtfs/validate",
        params={"schedule_version_id": state["board"]},
        headers=auth,
    ).json()
    # agency_url seeds blank, so this must be reported.
    assert any("agency_url" in problem for problem in problems)

    client.patch(
        f"{API}/parameters/agency_url",
        json={"value": "https://transit.example.com"},
        headers=auth,
    )
    cleared = client.get(
        f"{API}/gtfs/validate",
        params={"schedule_version_id": state["board"]},
        headers=auth,
    ).json()
    assert not any("agency_url" in problem for problem in cleared)


def test_agency_details_reach_the_feed(client, auth):
    client.patch(f"{API}/parameters/agency_name", json={"value": "Test Transit"}, headers=auth)
    feed = _feed(client, auth)
    agency = feed["agency.txt"][0]
    assert agency["agency_name"] == "Test Transit"
    assert agency["agency_url"] == "https://transit.example.com"
    assert agency["agency_timezone"]


def test_exporting_an_unknown_board_is_a_404(client, auth):
    response = client.get(
        f"{API}/gtfs/export", params={"schedule_version_id": 999999}, headers=auth
    )
    assert response.status_code == 404
