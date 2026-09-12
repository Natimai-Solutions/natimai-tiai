"""Per-account console preferences (need a database).

The machine list remembers which columns it shows and in what order — on the
account, not in the browser, so the choice follows the operator from one
workstation to the next. The server stores one JSON document per account,
merges writes key by key, and bounds its size.
"""


async def _login(client, db_session, email: str) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email=email,
        password="pw-long-enough",
        groups=[BuiltinGroup.READONLY],
    )
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "pw-long-enough"}
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_a_new_account_starts_with_no_preferences(client, db_session):
    headers = await _login(client, db_session, "fresh@test.local")
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["preferences"] == {}


async def test_preferences_are_merged_key_by_key(client, db_session):
    headers = await _login(client, db_session, "merge@test.local")
    columns = ["hostname", "room", "agent", "last_seen"]
    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"preferences": {"machines_columns": columns}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["preferences"] == {"machines_columns": columns}

    # Another page stores its own key: the first one is untouched.
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"preferences": {"theme": "dark"}}
    )
    assert resp.json()["preferences"] == {"machines_columns": columns, "theme": "dark"}

    # Null removes a key; a key not sent is left alone.
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"preferences": {"theme": None}}
    )
    assert resp.json()["preferences"] == {"machines_columns": columns}

    # And it is stored, not echoed: a fresh read says the same.
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["preferences"] == {"machines_columns": columns}


async def test_the_cadence_and_the_preferences_are_independent(client, db_session):
    headers = await _login(client, db_session, "both@test.local")
    await client.patch(
        "/api/v1/auth/me", headers=headers, json={"preferences": {"a": 1}}
    )
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"email_preference": "none"}
    )
    body = resp.json()
    assert body["email_preference"] == "none"
    assert body["preferences"] == {"a": 1}


async def test_preferences_are_private_to_the_account(client, db_session):
    one = await _login(client, db_session, "one@test.local")
    two = await _login(client, db_session, "two@test.local")
    await client.patch(
        "/api/v1/auth/me",
        headers=one,
        json={"preferences": {"machines_columns": ["hostname"]}},
    )
    assert (await client.get("/api/v1/auth/me", headers=two)).json()[
        "preferences"
    ] == {}


async def test_the_document_is_bounded(client, db_session):
    headers = await _login(client, db_session, "greedy@test.local")
    # Too many keys at once is refused by the schema.
    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"preferences": {f"k{i}": i for i in range(51)}},
    )
    assert resp.status_code == 422
    # A key too long as well.
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"preferences": {"k" * 65: 1}}
    )
    assert resp.status_code == 422
    # And a document that grows past the byte budget across two writes.
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"preferences": {"blob": "x" * 9000}}
    )
    assert resp.status_code == 200
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"preferences": {"blob2": "x" * 9000}}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "request.validation_error"
    # The refused write left the document as it was.
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert set(me["preferences"]) == {"blob"}
