"""Phase 10: the duty builder and its rule checks.

Builds on the network created in test_api.py, which runs first.
"""

import datetime as dt

from app.config import settings

from tests.test_api import state

API = settings.api_prefix

roster: dict = {}


def _duty_codes(report: dict) -> set[str]:
    return {issue["code"] for issue in report["issues"]}


def test_create_a_duty(client, auth):
    driver = client.get(f"{API}/drivers", headers=auth).json()["items"][0]
    roster["driver"] = driver["id"]

    response = client.post(
        f"{API}/duties",
        json={
            "name": "D1",
            "date": dt.date.today().isoformat(),
            "schedule_version_id": state["board"],
            "driver_id": driver["id"],
        },
        headers=auth,
    )
    assert response.status_code == 201, response.text
    roster["duty"] = response.json()["id"]
    # An empty duty is a warning, not an error -- it is a legitimate
    # intermediate state while building.
    assert response.json()["validation"]["issues"][0]["code"] == "DUTY_EMPTY"


def test_block_segment_takes_its_times_from_the_block(client, auth):
    """The duty stores a range, not a copy of the schedule."""
    response = client.put(
        f"{API}/duties/{roster['duty']}/pieces",
        json={
            "pieces": [
                {
                    "sequence": 1, "piece_type": "sign_on",
                    "location_id": state["depot"],
                    "start_seconds": "05:30", "end_seconds": "05:45",
                },
                {"sequence": 2, "piece_type": "block_segment", "block_id": state["block"]},
                {
                    "sequence": 3, "piece_type": "sign_off",
                    "location_id": state["depot"],
                    "start_seconds": "06:55", "end_seconds": "07:05",
                },
            ]
        },
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    segment = body["pieces"][1]
    assert segment["start_seconds"] is None  # nothing duplicated
    assert segment["effective_start_seconds"] == "05:45:00"  # the block's pull-out
    assert segment["effective_end_seconds"] == "06:55:00"  # the block's pull-in
    assert segment["covers_piece_count"] == 5

    assert body["start_seconds"] == "05:30:00"
    assert body["end_seconds"] == "07:05:00"
    assert body["driving_minutes"] == 70
    assert body["working_minutes"] == 95


def test_a_clean_duty_passes_the_rule_checks(client, auth):
    report = client.get(f"{API}/duties/{roster['duty']}/validate", headers=auth).json()
    assert report["ok"] is True, report["issues"]
    codes = _duty_codes(report)
    assert "NO_SIGN_ON" not in codes
    assert "NO_SIGN_OFF" not in codes


def test_overlapping_pieces_are_an_error(client, auth):
    """A driver cannot be in two places at once."""
    client.put(
        f"{API}/duties/{roster['duty']}/pieces",
        json={
            "pieces": [
                {
                    "sequence": 1, "piece_type": "sign_on",
                    "location_id": state["depot"],
                    "start_seconds": "05:30", "end_seconds": "06:30",
                },
                {"sequence": 2, "piece_type": "block_segment", "block_id": state["block"]},
            ]
        },
        headers=auth,
    )
    report = client.get(f"{API}/duties/{roster['duty']}/validate", headers=auth).json()
    assert "DUTY_PIECE_OVERLAP" in _duty_codes(report)
    assert report["ok"] is False


def test_parameter_violations_are_reported_but_never_block_the_save(client, auth):
    """Tighten a parameter and the same duty starts failing -- §4 step 5."""
    original = client.get(
        f"{API}/parameters/effective", headers=auth
    ).json()["max_driving_minutes_per_day"]

    client.patch(
        f"{API}/parameters/max_driving_minutes_per_day", json={"value": "30"}, headers=auth
    )

    saved = client.put(
        f"{API}/duties/{roster['duty']}/pieces",
        json={
            "pieces": [
                {
                    "sequence": 1, "piece_type": "sign_on",
                    "location_id": state["depot"],
                    "start_seconds": "05:30", "end_seconds": "05:45",
                },
                {"sequence": 2, "piece_type": "block_segment", "block_id": state["block"]},
            ]
        },
        headers=auth,
    )
    # The save succeeds even though the duty now breaks the rule.
    assert saved.status_code == 200
    assert "MAX_DRIVING_EXCEEDED" in _duty_codes(saved.json()["validation"])

    client.patch(
        f"{API}/parameters/max_driving_minutes_per_day",
        json={"value": str(original)},
        headers=auth,
    )


def test_missing_break_is_flagged_once_driving_is_long_enough(client, auth):
    client.patch(
        f"{API}/parameters/min_driving_minutes_before_break_required",
        json={"value": "30"},
        headers=auth,
    )
    report = client.get(f"{API}/duties/{roster['duty']}/validate", headers=auth).json()
    assert "INSUFFICIENT_BREAK" in _duty_codes(report)

    client.patch(
        f"{API}/parameters/min_driving_minutes_before_break_required",
        json={"value": "240"},
        headers=auth,
    )


def test_splitting_a_block_between_two_drivers(client, auth):
    """The AM driver takes pieces 1-2, the PM driver 3-5."""
    today = dt.date.today().isoformat()
    am = client.put(
        f"{API}/duties/{roster['duty']}/pieces",
        json={
            "pieces": [
                {
                    "sequence": 1, "piece_type": "sign_on",
                    "location_id": state["depot"],
                    "start_seconds": "05:30", "end_seconds": "05:45",
                },
                {
                    "sequence": 2, "piece_type": "block_segment",
                    "block_id": state["block"],
                    "from_block_piece_sequence": 1,
                    "to_block_piece_sequence": 2,
                },
            ]
        },
        headers=auth,
    ).json()
    assert am["pieces"][1]["covers_piece_count"] == 2
    # Pieces 1-2 are the pull-out and the first trip: 05:45 to 06:09:30.
    assert am["pieces"][1]["effective_end_seconds"] == "06:09:30"

    pm_duty = client.post(
        f"{API}/duties",
        json={
            "name": "D2",
            "date": today,
            "schedule_version_id": state["board"],
        },
        headers=auth,
    ).json()
    roster["pm_duty"] = pm_duty["id"]

    pm = client.put(
        f"{API}/duties/{pm_duty['id']}/pieces",
        json={
            "pieces": [
                {
                    "sequence": 1, "piece_type": "block_segment",
                    "block_id": state["block"],
                    "from_block_piece_sequence": 3,
                    "to_block_piece_sequence": 5,
                }
            ]
        },
        headers=auth,
    ).json()
    assert pm["pieces"][0]["covers_piece_count"] == 3
    # Pieces 3-5 start with the deadhead at 06:10, not the trip at 06:30.
    assert pm["pieces"][0]["effective_start_seconds"] == "06:10:00"
    assert pm["pieces"][0]["effective_end_seconds"] == "06:55:00"

    # Between the two duties the whole block is now staffed.
    coverage = client.get(
        f"{API}/duties/coverage/report",
        params={"schedule_version_id": state["board"], "date": today},
        headers=auth,
    ).json()
    block_row = next(c for c in coverage if c["block_id"] == state["block"])
    assert block_row["fully_covered"] is True
    assert block_row["uncovered_sequences"] == []


def test_direct_handover_is_allowed_but_flagged(client, auth):
    """§10's second question: allowed by default, blocked only on request."""
    report = client.get(f"{API}/duties/{roster['pm_duty']}/validate", headers=auth).json()
    relief = [i for i in report["issues"] if i["code"] == "RELIEF_WITHOUT_BREAK"]
    assert relief, "a partial block with no break should be noted"
    assert relief[0]["severity"] == "info"

    client.patch(
        f"{API}/parameters/require_break_at_driver_changeover",
        json={"value": "true"},
        headers=auth,
    )
    stricter = client.get(f"{API}/duties/{roster['pm_duty']}/validate", headers=auth).json()
    relief = [i for i in stricter["issues"] if i["code"] == "RELIEF_WITHOUT_BREAK"]
    assert relief[0]["severity"] == "error"

    client.patch(
        f"{API}/parameters/require_break_at_driver_changeover",
        json={"value": "false"},
        headers=auth,
    )


def test_a_driver_cannot_work_two_overlapping_duties(client, auth):
    client.patch(
        f"{API}/duties/{roster['pm_duty']}", json={"driver_id": roster["driver"]}, headers=auth
    )
    report = client.get(f"{API}/duties/{roster['pm_duty']}/validate", headers=auth).json()
    assert "DRIVER_DOUBLE_BOOKED" not in _duty_codes(report)

    # Now make them overlap.
    client.put(
        f"{API}/duties/{roster['pm_duty']}/pieces",
        json={
            "pieces": [
                {
                    "sequence": 1, "piece_type": "block_segment",
                    "block_id": state["block"],
                    "from_block_piece_sequence": 1,
                    "to_block_piece_sequence": 5,
                }
            ]
        },
        headers=auth,
    )
    clash = client.get(f"{API}/duties/{roster['pm_duty']}/validate", headers=auth).json()
    assert "DRIVER_DOUBLE_BOOKED" in _duty_codes(clash)

    client.patch(f"{API}/duties/{roster['pm_duty']}", json={"driver_id": None}, headers=auth)


def test_a_block_from_another_board_is_rejected(client, auth):
    other_board = client.post(
        f"{API}/schedule-versions",
        json={
            "name": "Unrelated board",
            "start_date": "2030-01-01",
            "end_date": "2030-12-31",
        },
        headers=auth,
    ).json()
    other_block = client.post(
        f"{API}/blocks",
        json={"schedule_version_id": other_board["id"], "name": "X1"},
        headers=auth,
    ).json()

    response = client.put(
        f"{API}/duties/{roster['duty']}/pieces",
        json={
            "pieces": [
                {"sequence": 1, "piece_type": "block_segment", "block_id": other_block["id"]}
            ]
        },
        headers=auth,
    )
    assert response.status_code == 422
    assert "different schedule board" in response.json()["detail"]


def test_duty_card_pdf_renders(client, auth):
    response = client.get(
        f"{API}/pdf/duty-card", params={"duty_id": roster["duty"]}, headers=auth
    )
    assert response.status_code == 200, response.text[:400]
    assert response.content[:5] == b"%PDF-"


def test_deleting_a_rostered_driver_is_refused(client, auth):
    client.patch(
        f"{API}/duties/{roster['duty']}", json={"driver_id": roster["driver"]}, headers=auth
    )
    response = client.delete(f"{API}/drivers/{roster['driver']}", headers=auth)
    assert response.status_code == 409
    assert "duties" in response.json()["detail"].lower()
