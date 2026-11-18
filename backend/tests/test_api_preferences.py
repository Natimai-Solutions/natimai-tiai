"""Per-account console preferences (need a database).

The machine list remembers which columns it shows and in what order — on the
account, not in the browser, so the choice follows the operator from one
workstation to the next. The server stores one JSON document per account,
merges writes key by key, and bounds its size.
"""

import pytest


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


async def test_concurrent_writes_of_distinct_keys_all_stick(client, db_session):
    """Eight pages saving eight different keys at the same instant: every key
    is kept. Each write is merged by the database on the row as it stands,
    not on the copy its request had read."""
    import asyncio

    headers = await _login(client, db_session, "busy@test.local")
    responses = await asyncio.gather(
        *(
            client.patch(
                "/api/v1/auth/me",
                headers=headers,
                json={"preferences": {f"page{i}": [i]}},
            )
            for i in range(8)
        )
    )
    assert [r.status_code for r in responses] == [200] * 8
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["preferences"] == {f"page{i}": [i] for i in range(8)}


async def test_a_null_key_is_removed_by_the_database_merge(client, db_session):
    headers = await _login(client, db_session, "tidy@test.local")
    await client.patch(
        "/api/v1/auth/me", headers=headers, json={"preferences": {"a": 1, "b": 2}}
    )
    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"preferences": {"a": None, "c": {"x": [1, 2]}}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["preferences"] == {"b": 2, "c": {"x": [1, 2]}}


def _nested(levels: int) -> list:
    """A list in a list in a list… ``levels`` deep."""
    value: list = []
    for _ in range(levels - 1):
        value = [value]
    return value


async def test_a_deeply_nested_value_is_refused(client, db_session):
    """Verification of v1.2.1, F7: the document was bounded in keys and in
    bytes, not in depth. A value nested 300 levels deep fits in 600 bytes,
    was stored, and could not be served back — every ``GET /auth/me`` of
    the account then answered 500 and its console no longer loaded."""
    from app.api.routes.auth import PREFERENCES_MAX_DEPTH

    headers = await _login(client, db_session, "deep@test.local")
    for levels in (PREFERENCES_MAX_DEPTH + 1, 300):
        resp = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"preferences": {"deep": _nested(levels)}},
        )
        assert resp.status_code == 422, resp.text
        # Inside an object as well as inside a list.
        resp = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"preferences": {"deep": {"a": _nested(levels - 1)}}},
        )
        assert resp.status_code == 422, resp.text
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["preferences"] == {}

    # What the console stores is nowhere near the limit, which is accepted.
    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"preferences": {"ok": _nested(PREFERENCES_MAX_DEPTH)}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["preferences"] == {"ok": _nested(PREFERENCES_MAX_DEPTH)}


async def test_a_value_stored_too_deep_does_not_brick_the_profile(client, db_session):
    """An account that stored such a value before the bound existed must
    load its console again, and be able to mend itself: the profile leaves
    out the key it cannot serve, and the other keys stay writable."""
    from sqlalchemy import update
    from sqlmodel import col

    from app.features.user.models import User

    headers = await _login(client, db_session, "bricked@test.local")
    await db_session.exec(
        update(User)
        .where(col(User.email) == "bricked@test.local")
        .values(preferences={"deep": _nested(300), "theme": "dark"})
    )
    await db_session.commit()

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["preferences"] == {"theme": "dark"}
    # Another key is saved as before…
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"preferences": {"columns": ["a"]}}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["preferences"] == {"theme": "dark", "columns": ["a"]}
    # …and the bad one is replaced or removed like any other.
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"preferences": {"deep": [1]}}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["preferences"]["deep"] == [1]


@pytest.mark.parametrize(
    "body",
    [
        # A lone surrogate: a string no UTF-8 text can carry.
        b'{"preferences": {"k": "\\ud83d"}}',
        b'{"preferences": {"k": ["a", {"b": "x\\udc00y"}]}}',
        b'{"preferences": {"\\ud83d": 1}}',
        b'{"preferences": {"k": {"\\ud83d": 1}}}',
        # Not JSON numbers, though Python reads them.
        b'{"preferences": {"k": NaN}}',
        b'{"preferences": {"k": [1, -Infinity]}}',
    ],
)
async def test_a_value_that_cannot_be_stored_is_refused(client, db_session, body):
    """A lone surrogate reached the database, which refused it: a 500.
    Refused with the rest of what a JSON document cannot hold."""
    headers = await _login(client, db_session, "odd@test.local")
    resp = await client.patch(
        "/api/v1/auth/me",
        headers={**headers, "Content-Type": "application/json"},
        content=body,
    )
    assert resp.status_code == 422, resp.text
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["preferences"] == {}
