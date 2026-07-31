"""Phase 11: the journey search.

Uses the network from test_api.py: pattern Alpha -> Bravo -> Charlie, three
weekday trips, plus a stop area joining Alpha and Bravo.
"""

import datetime as dt

from app.config import settings

from tests.test_api import state

API = settings.api_prefix


def _next_weekday() -> dt.date:
    """The board's only calendar runs Monday to Friday."""
    date = dt.date.today()
    while date.weekday() > 4:
        date += dt.timedelta(days=1)
    return date


def _search(client, auth, **overrides):
    payload = {
        "from_location_id": state["stops"][0],
        "to_location_id": state["stops"][2],
        "date": _next_weekday().isoformat(),
        "depart_after": "05:00",
    }
    payload.update(overrides)
    response = client.post(f"{API}/itinerary/search", json=payload, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()["itineraries"]


def test_finds_a_direct_journey(client, auth):
    results = _search(client, auth)
    assert results, "Alpha to Charlie is a single ride on the seeded pattern"

    first = results[0]
    assert first["transfer_count"] == 0
    assert first["depart_seconds"] == "06:00:30"
    assert first["arrive_seconds"] == "06:09:30"
    assert first["duration_seconds"] == 9 * 60

    leg = first["legs"][0]
    assert leg["kind"] == "ride"
    assert leg["from_location_name"] == "Alpha"
    assert leg["to_location_name"] == "Charlie"
    # Bravo is passed through, not changed at.
    assert leg["intermediate_stop_count"] == 1


def test_departure_time_is_respected(client, auth):
    results = _search(client, auth, depart_after="06:30")
    assert results
    assert results[0]["depart_seconds"] >= "06:30:00"


def test_alternatives_are_genuinely_different_departures(client, auth):
    results = _search(client, auth, max_results=3)
    departures = [r["depart_seconds"] for r in results]
    assert len(departures) == len(set(departures)), "each option must be a distinct run"


def test_no_service_on_a_date_the_calendar_excludes(client, auth):
    saturday = dt.date.today()
    while saturday.weekday() != 5:
        saturday += dt.timedelta(days=1)
    assert _search(client, auth, date=saturday.isoformat()) == []


def test_a_calendar_exception_removes_the_service(client, auth):
    """The classic bug this guards: a public holiday running a weekday service."""
    date = _next_weekday()
    assert _search(client, auth, date=date.isoformat())

    exception = client.post(
        f"{API}/calendar-exceptions",
        json={
            "calendar_id": state["calendar"],
            "date": date.isoformat(),
            "exception_type": "removed",
            "notes": "Public holiday",
        },
        headers=auth,
    )
    assert exception.status_code == 201, exception.text

    assert _search(client, auth, date=date.isoformat()) == []

    client.delete(f"{API}/calendar-exceptions/{exception.json()['id']}", headers=auth)
    assert _search(client, auth, date=date.isoformat())


def test_fare_is_attached_to_the_journey(client, auth):
    results = _search(client, auth)
    assert results[0]["fare_price_cents"] == 250
    assert results[0]["fare_currency"] == "EUR"


def test_same_origin_and_destination_is_rejected(client, auth):
    response = client.post(
        f"{API}/itinerary/search",
        json={
            "from_location_id": state["stops"][0],
            "to_location_id": state["stops"][0],
            "date": _next_weekday().isoformat(),
        },
        headers=auth,
    )
    assert response.status_code == 422


def test_walking_uses_only_declared_transfers(client, auth):
    """Charlie has no stop area and no transfer row, so nothing walks to it.

    Alpha and Bravo do share an area, so a walk between them exists. This is
    the guarantee from §1a: connectivity is stated, never inferred from
    coordinates.
    """
    edges = client.get(f"{API}/location-transfers/graph/edges", headers=auth).json()
    involved = {e["from_location_id"] for e in edges} | {e["to_location_id"] for e in edges}
    assert state["stops"][2] not in involved
    assert state["stops"][0] in involved
