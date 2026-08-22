"""Multi-environment isolation.

The point of a database per environment is that data cannot leak between
cities. These tests assert exactly that, which is why the suite runs on
PostgreSQL — SQLite has no way to express it.

Runs last (alphabetically after test_api) so the network built by the other
suites exists to be *not* visible from a second environment.
"""

from app.config import settings

from tests.test_api import state

API = settings.api_prefix

created: dict = {}


def _env(key: str) -> dict:
    return {"X-Environment": key}


def test_the_existing_database_registered_itself_as_default(client, auth):
    """Upgrading a single-database install must cost no data migration."""
    rows = client.get(f"{API}/environments", headers=auth).json()
    assert len(rows) == 1

    default = rows[0]
    assert default["key"] == "default"
    assert default["is_default"] is True
    assert default["is_current"] is True
    created["default_id"] = default["id"]


def test_creating_an_environment_provisions_an_empty_one(client, auth):
    response = client.post(
        f"{API}/environments",
        json={"key": "city2", "name": "City Two Transit"},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    created["city2_id"] = body["id"]
    assert body["key"] == "city2"
    assert body["database_name"].endswith("city2")
    assert body["is_default"] is False


def test_the_new_environment_is_empty(client, auth):
    """The whole point: city2 cannot see city1's network."""
    page = client.get(f"{API}/locations", headers={**auth, **_env("city2")}).json()
    assert page["total"] == 0

    lines = client.get(f"{API}/lines", headers={**auth, **_env("city2")}).json()
    assert lines["total"] == 0

    boards = client.get(f"{API}/schedule-versions", headers={**auth, **_env("city2")}).json()
    assert boards["total"] == 0


def test_the_original_environment_still_has_its_data(client, auth):
    page = client.get(f"{API}/locations", headers=auth).json()
    assert page["total"] > 0
    assert any(row["id"] == state["depot"] for row in page["items"])


def test_writes_land_only_in_the_environment_they_were_made_in(client, auth):
    response = client.post(
        f"{API}/locations",
        json={"name": "City Two Depot", "code": "C2DEP", "location_type": "depot"},
        headers={**auth, **_env("city2")},
    )
    assert response.status_code == 201, response.text
    created["c2_depot"] = response.json()["id"]

    in_city2 = client.get(f"{API}/locations", headers={**auth, **_env("city2")}).json()
    assert [row["name"] for row in in_city2["items"]] == ["City Two Depot"]

    # The same code exists in city2 but must not appear in the default
    # environment — and must not collide with its unique constraint either.
    in_default = client.get(
        f"{API}/locations", params={"q": "C2DEP"}, headers=auth
    ).json()
    assert in_default["total"] == 0


def test_the_same_code_can_exist_in_both_environments(client, auth):
    """Unique constraints are per-database, which is the intended behaviour."""
    response = client.post(
        f"{API}/locations",
        json={"name": "Default-side C2DEP", "code": "C2DEP", "location_type": "depot"},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    client.delete(f"{API}/locations/{response.json()['id']}", headers=auth)


def test_a_new_environment_has_its_own_operating_parameters(client, auth):
    values = client.get(
        f"{API}/parameters/effective", headers={**auth, **_env("city2")}
    ).json()
    assert values["min_break_minutes"] == 45

    # Changing one in city2 must not touch the default environment.
    client.patch(
        f"{API}/parameters/min_break_minutes",
        json={"value": "30"},
        headers={**auth, **_env("city2")},
    )
    assert (
        client.get(f"{API}/parameters/effective", headers={**auth, **_env("city2")})
        .json()["min_break_minutes"]
        == 30
    )
    assert (
        client.get(f"{API}/parameters/effective", headers=auth)
        .json()["min_break_minutes"]
        == 45
    )


def test_each_environment_names_itself(client, auth):
    client.patch(
        f"{API}/parameters/instance_name",
        json={"value": "City Two"},
        headers={**auth, **_env("city2")},
    )
    config = client.get(f"{API}/config", headers=_env("city2")).json()
    assert config["app_name"] == "City Two"
    assert config["environment_key"] == "city2"


def test_users_are_shared_across_environments(client, auth):
    """One login reaches every city."""
    from_default = client.get(f"{API}/auth/me", headers=auth).json()
    from_city2 = client.get(f"{API}/auth/me", headers={**auth, **_env("city2")}).json()
    assert from_default["id"] == from_city2["id"]

    users = client.get(f"{API}/users", headers={**auth, **_env("city2")}).json()
    assert users["total"] >= 1


def test_an_unknown_environment_is_refused_not_silently_defaulted(client, auth):
    """Falling back would silently show another city's data."""
    response = client.get(f"{API}/locations", headers={**auth, **_env("nowhere")})
    assert response.status_code == 404
    assert "nowhere" in response.json()["detail"]


def test_a_bad_key_is_rejected_before_a_database_is_made(client, auth):
    for bad in ("2city", "City-One", "with space", "a", "postgres"):
        response = client.post(
            f"{API}/environments", json={"key": bad, "name": "x"}, headers=auth
        )
        assert response.status_code == 422, f"{bad} should be rejected"


def test_duplicate_keys_are_refused(client, auth):
    response = client.post(
        f"{API}/environments", json={"key": "city2", "name": "Again"}, headers=auth
    )
    assert response.status_code == 409


def test_only_an_admin_can_create_an_environment(client, auth):
    token = client.post(
        f"{API}/auth/login", data={"username": "viewer1", "password": "viewer-password"}
    ).json()["access_token"]

    response = client.post(
        f"{API}/environments",
        json={"key": "city9", "name": "Nope"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    # But everyone may see the list — the switcher needs it.
    listed = client.get(
        f"{API}/environments", headers={"Authorization": f"Bearer {token}"}
    )
    assert listed.status_code == 200


def test_the_default_cannot_be_disabled_or_deleted(client, auth):
    disabled = client.patch(
        f"{API}/environments/{created['default_id']}",
        json={"is_active": False},
        headers=auth,
    )
    assert disabled.status_code == 409

    # Deleting the one you are working in is refused too.
    deleted = client.delete(f"{API}/environments/{created['default_id']}", headers=auth)
    assert deleted.status_code == 409


def test_making_another_environment_the_default_moves_the_flag(client, auth):
    client.post(f"{API}/environments/{created['city2_id']}/make-default", headers=auth)
    rows = {row["key"]: row for row in client.get(f"{API}/environments", headers=auth).json()}
    assert rows["city2"]["is_default"] is True
    assert rows["default"]["is_default"] is False

    # Put it back, so later assertions about the default still hold.
    client.post(f"{API}/environments/{created['default_id']}/make-default", headers=auth)


def test_unregistering_keeps_the_database(client, auth):
    response = client.post(
        f"{API}/environments", json={"key": "city3", "name": "City Three"}, headers=auth
    )
    environment_id = response.json()["id"]

    removed = client.delete(f"{API}/environments/{environment_id}", headers=auth)
    assert removed.status_code == 204

    keys = {row["key"] for row in client.get(f"{API}/environments", headers=auth).json()}
    assert "city3" not in keys

    # Re-registering the same key reuses the database that was left behind.
    again = client.post(
        f"{API}/environments", json={"key": "city3", "name": "City Three"}, headers=auth
    )
    assert again.status_code == 201
    client.delete(
        f"{API}/environments/{again.json()['id']}", params={"drop_data": True}, headers=auth
    )
