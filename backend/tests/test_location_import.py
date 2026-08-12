"""CSV import for locations.

Runs after test_api.py (alphabetically), which builds the base network:
depot "Test Depot" (DEP), stops Alpha (S0), Bravo (S1), Charlie (S2), fare
zones "Zone A" / "Zone B", stop area "Test Corner".
"""

from app.config import settings

from tests.test_api import state

API = settings.api_prefix


def _post(client, auth, text, *, dry_run=True, replace_attributes=False, name="import.csv"):
    payload = text.encode("utf-8") if isinstance(text, str) else text
    response = client.post(
        f"{API}/locations/import",
        files={"file": (name, payload, "text/csv")},
        params={"dry_run": dry_run, "replace_attributes": replace_attributes},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _by_code(client, auth, code):
    page = client.get(f"{API}/locations", params={"q": code}, headers=auth).json()
    return next((row for row in page["items"] if row["code"] == code), None)


def test_a_dry_run_writes_nothing(client, auth):
    before = client.get(f"{API}/locations", params={"limit": 1}, headers=auth).json()["total"]

    report = _post(
        client,
        auth,
        "name,code,location_type,lat,lon\n" "Imported One,IMP1,stop,52.1,4.1\n",
    )
    assert report["dry_run"] is True
    assert report["ok"] is True
    assert report["created"] == 1

    after = client.get(f"{API}/locations", params={"limit": 1}, headers=auth).json()["total"]
    assert after == before, "a dry run must leave the database untouched"
    assert _by_code(client, auth, "IMP1") is None


def test_applying_creates_the_rows(client, auth):
    report = _post(
        client,
        auth,
        "name,code,location_type,lat,lon\n"
        "Imported One,IMP1,stop,52.1,4.1\n"
        "Imported Depot,IMPD,depot,52.2,4.2\n",
        dry_run=False,
    )
    assert report["ok"] is True
    assert report["created"] == 2

    created = _by_code(client, auth, "IMP1")
    assert created is not None
    assert created["location_type"] == "stop"
    assert created["lat"] == 52.1


def test_matching_on_code_updates_rather_than_duplicating(client, auth):
    report = _post(
        client,
        auth,
        "code,lat,lon\nIMP1,53.5,5.5\n",
        dry_run=False,
    )
    assert report["updated"] == 1
    assert report["created"] == 0

    updated = _by_code(client, auth, "IMP1")
    assert updated["lat"] == 53.5
    # The name was not in the file, so it must be untouched.
    assert updated["name"] == "Imported One"


def test_blank_cells_leave_existing_values_alone(client, auth):
    report = _post(client, auth, "code,name,lat,lon\nIMP1,,,\n", dry_run=False)
    assert report["rows"][0]["action"] == "skipped"

    row = _by_code(client, auth, "IMP1")
    assert row["lat"] == 53.5
    assert row["name"] == "Imported One"


def test_unknown_columns_become_attributes(client, auth):
    report = _post(
        client,
        auth,
        "code,has_shelter,park_and_ride\nIMP1,true,no\n",
        dry_run=False,
    )
    assert report["attribute_columns"] == ["has_shelter", "park_and_ride"]
    assert report["updated"] == 1

    row = _by_code(client, auth, "IMP1")
    attributes = {a["attribute_key"]: a["attribute_value"] for a in row["attributes"]}
    assert attributes["has_shelter"] == "true"
    assert attributes["park_and_ride"] == "no"


def test_attributes_are_merged_unless_replacement_is_asked_for(client, auth):
    _post(client, auth, "code,lit\nIMP1,true\n", dry_run=False)
    row = _by_code(client, auth, "IMP1")
    keys = {a["attribute_key"] for a in row["attributes"]}
    assert keys == {"has_shelter", "park_and_ride", "lit"}

    # Explicit opt-in: this file is the whole truth.
    _post(client, auth, "code,lit\nIMP1,false\n", dry_run=False, replace_attributes=True)
    row = _by_code(client, auth, "IMP1")
    attributes = {a["attribute_key"]: a["attribute_value"] for a in row["attributes"]}
    assert attributes == {"lit": "false"}


def test_zones_and_areas_resolve_by_name(client, auth):
    report = _post(
        client,
        auth,
        "code,zone,area\nIMP1,Zone A,Test Corner\n",
        dry_run=False,
    )
    assert report["ok"] is True, report["rows"]

    row = _by_code(client, auth, "IMP1")
    assert row["zone_name"] == "Zone A"
    assert row["area_name"] == "Test Corner"


def test_a_depot_cannot_be_put_in_a_stop_area(client, auth):
    report = _post(client, auth, "code,area\nIMPD,Test Corner\n")
    assert report["ok"] is False
    assert "stop area" in report["rows"][0]["message"]


def test_unknown_references_are_reported_with_the_line_number(client, auth):
    report = _post(
        client,
        auth,
        "name,code,zone\nGood,IMPZ1,Zone A\nBad,IMPZ2,Zone Q\n",
    )
    assert report["failed"] == 1
    failure = next(r for r in report["rows"] if r["action"] == "failed")
    assert failure["line"] == 3  # header is line 1
    assert "Zone Q" in failure["message"]


def test_nothing_is_written_when_any_row_fails(client, auth):
    """A half-applied import is worse than none."""
    report = _post(
        client,
        auth,
        "name,code,location_type\n"
        "Should Not Exist,IMPX1,stop\n"
        "Broken,IMPX2,spaceship\n",
        dry_run=False,
    )
    assert report["ok"] is False
    assert _by_code(client, auth, "IMPX1") is None


def test_semicolon_files_from_a_european_excel(client, auth):
    report = _post(client, auth, "name;code;lat;lon\nSemi Stop;IMPS;52,5;4,5\n")
    assert report["delimiter"] == ";"
    assert report["ok"] is True
    assert report["created"] == 1
    # A comma decimal separator is a number, not a broken field.
    assert report["rows"][0]["action"] == "created"


def test_a_utf8_bom_does_not_corrupt_the_first_header(client, auth):
    """Our own export writes a BOM so Excel opens it correctly."""
    payload = "﻿name,code\nBom Stop,IMPB\n".encode("utf-8")
    report = _post(client, auth, payload)
    assert report["ok"] is True
    assert "name" in report["columns"]
    assert report["created"] == 1


def test_an_export_round_trips(client, auth):
    """Download, upload unchanged: everything matches, nothing changes."""
    export = client.get(f"{API}/csv/locations", headers=auth)
    assert export.status_code == 200

    report = _post(client, auth, export.content, name="locations.csv")
    assert report["ok"] is True, report["rows"]
    assert report["created"] == 0, "a round trip must not duplicate anything"
    assert report["failed"] == 0


def test_a_bad_id_is_an_error_not_a_silent_insert(client, auth):
    report = _post(client, auth, "id,name\n999999,Ghost\n")
    assert report["ok"] is False
    assert "does not exist" in report["rows"][0]["message"]


def test_a_file_without_usable_headers_is_rejected_clearly(client, auth):
    report = _post(client, auth, "colour,size\nred,large\n")
    assert report["fatal"] is not None
    assert "name" in report["fatal"]


def test_an_empty_file_is_rejected(client, auth):
    report = _post(client, auth, "")
    assert report["fatal"] == "The file is empty."


def test_a_viewer_cannot_import(client, auth):
    token = client.post(
        f"{API}/auth/login", data={"username": "viewer1", "password": "viewer-password"}
    ).json()["access_token"]

    response = client.post(
        f"{API}/locations/import",
        files={"file": ("x.csv", b"name,code\nNope,NOPE\n", "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
