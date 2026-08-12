"""Stop skipping: a trip that runs past a stop without calling.

Runs last (alphabetically) because it edits a trip the earlier suites read.
Uses trips[2], the one no block ever claimed.
"""

from app.config import settings

from tests.test_api import state

API = settings.api_prefix


def _detail(client, auth, trip_id: int) -> dict:
    response = client.get(f"{API}/trips/{trip_id}/detail", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def test_detail_lists_every_pattern_stop_not_only_the_called_ones(client, auth):
    """The editor cannot offer to skip a stop it was never told about."""
    detail = _detail(client, auth, state["trips"][2])
    assert len(detail["calls"]) == 3
    assert [c["sequence"] for c in detail["calls"]] == [1, 2, 3]
    assert all(c["skipped"] is False for c in detail["calls"])
    assert detail["calls"][1]["location_name"] == "Bravo"


def test_omitting_a_stop_time_skips_that_stop(client, auth):
    trip_id = state["trips"][2]
    detail = _detail(client, auth, trip_id)
    calls = detail["calls"]

    # Keep the first and last, drop the middle one.
    response = client.patch(
        f"{API}/trips/{trip_id}",
        json={
            "stop_times": [
                {
                    "pattern_stop_id": call["pattern_stop_id"],
                    "arrival_seconds": call["arrival_seconds"],
                    "departure_seconds": call["departure_seconds"],
                }
                for call in (calls[0], calls[2])
            ]
        },
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert len(body["stop_times"]) == 2
    assert [c["skipped"] for c in body["calls"]] == [False, True, False]
    # A skipped stop carries no times at all, rather than a blank call.
    assert body["calls"][1]["arrival_seconds"] is None
    assert body["calls"][1]["departure_seconds"] is None


def test_the_skipped_stop_shows_as_a_gap_in_the_timetable(client, auth):
    grid = client.get(
        f"{API}/timetables",
        params={"schedule_version_id": state["board"], "pattern_id": state["pattern"]},
        headers=auth,
    ).json()

    column = grid["trip_ids"].index(state["trips"][2])
    assert grid["rows"][0]["cells"][column]["departure_seconds"] is not None
    assert grid["rows"][1]["cells"][column]["departure_seconds"] is None  # skipped
    assert grid["rows"][2]["cells"][column]["departure_seconds"] is not None


def test_a_skipped_stop_is_absent_from_the_gtfs_feed(client, auth):
    import csv
    import io
    import zipfile

    response = client.get(
        f"{API}/gtfs/export",
        params={"schedule_version_id": state["board"]},
        headers=auth,
    )
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    rows = list(
        csv.DictReader(io.StringIO(archive.read("stop_times.txt").decode("utf-8")))
    )

    served = [r for r in rows if r["trip_id"] == str(state["trips"][2])]
    assert len(served) == 2
    # Renumbered densely, so a reader never sees a gap in stop_sequence.
    assert [r["stop_sequence"] for r in served] == ["1", "2"]


def test_a_trip_cannot_skip_its_way_down_to_one_stop(client, auth):
    trip_id = state["trips"][2]
    calls = _detail(client, auth, trip_id)["calls"]
    kept = next(c for c in calls if not c["skipped"])

    response = client.patch(
        f"{API}/trips/{trip_id}",
        json={
            "stop_times": [
                {
                    "pattern_stop_id": kept["pattern_stop_id"],
                    "arrival_seconds": kept["arrival_seconds"],
                    "departure_seconds": kept["departure_seconds"],
                }
            ]
        },
        headers=auth,
    )
    assert response.status_code == 422
    assert "at least two stops" in response.json()["detail"]


def test_times_must_run_forwards_along_the_route(client, auth):
    trip_id = state["trips"][2]
    calls = _detail(client, auth, trip_id)["calls"]
    served = [c for c in calls if not c["skipped"]]

    response = client.patch(
        f"{API}/trips/{trip_id}",
        json={
            "stop_times": [
                {
                    "pattern_stop_id": served[0]["pattern_stop_id"],
                    "arrival_seconds": "08:00:00",
                    "departure_seconds": "08:00:00",
                },
                {
                    "pattern_stop_id": served[1]["pattern_stop_id"],
                    "arrival_seconds": "07:00:00",
                    "departure_seconds": "07:00:00",
                },
            ]
        },
        headers=auth,
    )
    assert response.status_code == 422
    assert "forwards along the route" in response.json()["detail"]


def test_restoring_the_stop_brings_the_call_back(client, auth):
    trip_id = state["trips"][2]
    calls = _detail(client, auth, trip_id)["calls"]

    response = client.patch(
        f"{API}/trips/{trip_id}",
        json={
            "stop_times": [
                {
                    "pattern_stop_id": call["pattern_stop_id"],
                    "arrival_seconds": call["arrival_seconds"] or "07:15:00",
                    "departure_seconds": call["departure_seconds"] or "07:15:00",
                }
                for call in calls
            ]
        },
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert all(c["skipped"] is False for c in response.json()["calls"])
