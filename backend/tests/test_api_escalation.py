"""No escalation through account management: an account only grants, and
only reaches, what it holds itself.

The actor of these tests is the case the rule exists for: a technician trusted
with the accounts (``user:read`` + ``user:write``) and with the everyday
commands, but not with the risky ones. Before the rule, ``user:write`` was
administrator in all but name — this file is the list of doors it opened.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import logging
import uuid

import pytest

STRONG = "correct-horse-battery"

# Lecture seule + account management + everyday commands; no risky command,
# no journal or maintenance writes — so « Techniciens » grants more than this.
TECH_PERMISSIONS = [
    "machine:read",
    "threat:read",
    "command:read",
    "room:read",
    "intervention:read",
    "check:read",
    "maintenance:read",
    "command:execute",
    "user:read",
    "user:write",
]


async def _login(client, email, password=STRONG):
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _user(db_session, email, groups):
    from app.features.user import crud

    user = await crud.create_user(
        db_session, email=email, password=STRONG, groups=groups
    )
    return str(user.id)


async def _builtin(db_session, key):
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    # The id is read before the commit, which expires every loaded attribute.
    group_id = str((await crud.builtin_group(db_session, BuiltinGroup(key))).id)
    await db_session.commit()
    return group_id


async def _group(db_session, name, permissions):
    from app.features.user import crud
    from app.features.user.models import Group

    group = Group(name=name)
    db_session.add(group)
    await db_session.flush()
    group_id = str(group.id)
    await crud.set_group_permissions(db_session, group, permissions)
    await db_session.commit()
    return group_id


@pytest.fixture
async def parc(client, db_session):
    """An administrator, a technician-manager, and a few accounts around them."""
    from app.features.user import crud

    await crud.ensure_builtin_groups(db_session)
    await db_session.commit()
    ids = {
        "admin_group": await _builtin(db_session, "admin"),
        "readonly_group": await _builtin(db_session, "readonly"),
        "technician_group": await _builtin(db_session, "technician"),
        "managers_group": await _group(
            db_session, "Gestion des comptes", TECH_PERMISSIONS
        ),
    }
    ids["admin"] = await _user(
        db_session, "admin@test.local", [uuid.UUID(ids["admin_group"])]
    )
    ids["tech"] = await _user(
        db_session, "tech@test.local", [uuid.UUID(ids["managers_group"])]
    )
    ids["readonly"] = await _user(
        db_session, "ro@test.local", [uuid.UUID(ids["readonly_group"])]
    )
    ids["technician"] = await _user(
        db_session, "technicien@test.local", [uuid.UUID(ids["technician_group"])]
    )
    ids["admin_headers"] = await _login(client, "admin@test.local")
    ids["tech_headers"] = await _login(client, "tech@test.local")
    return ids


def _refused(resp, *, missing=None, admin=None):
    assert resp.status_code == 403, resp.text
    error = resp.json()["error"]
    assert error["code"] == "auth.permission.escalation"
    if missing is not None:
        assert error["details"]["missing"] == missing
    if admin is not None:
        assert error["details"]["admin"] is admin


# --- (a) Groups -----------------------------------------------------------------


async def test_cannot_create_a_group_with_a_permission_one_lacks(client, parc):
    resp = await client.post(
        "/api/v1/groups",
        headers=parc["tech_headers"],
        json={"name": "Redémarreurs", "permissions": ["risky_command:execute"]},
    )
    _refused(resp, missing=["risky_command:execute"], admin=False)
    groups = (await client.get("/api/v1/groups", headers=parc["tech_headers"])).json()
    assert "Redémarreurs" not in {g["name"] for g in groups}


async def test_may_compose_a_group_from_ones_own_permissions(client, parc):
    resp = await client.post(
        "/api/v1/groups",
        headers=parc["tech_headers"],
        json={"name": "Scan", "permissions": ["machine:read", "command:execute"]},
    )
    assert resp.status_code == 201, resp.text


async def test_cannot_touch_the_administrators_group(client, parc):
    resp = await client.patch(
        f"/api/v1/groups/{parc['admin_group']}",
        headers=parc["tech_headers"],
        json={"name": "Renommé"},
    )
    _refused(resp, admin=True)


async def test_cannot_edit_a_group_granting_more_than_one_holds(client, parc):
    """Stripping « Techniciens » of the risky commands would change what more
    powerful accounts may do: out of reach, like the accounts themselves."""
    for payload in (
        {"name": "Renommé"},
        {"permissions": ["machine:read"]},
    ):
        resp = await client.patch(
            f"/api/v1/groups/{parc['technician_group']}",
            headers=parc["tech_headers"],
            json=payload,
        )
        _refused(resp, admin=False)


async def test_cannot_add_a_permission_one_lacks_to_a_group_in_reach(client, parc):
    resp = await client.patch(
        f"/api/v1/groups/{parc['readonly_group']}",
        headers=parc["tech_headers"],
        json={"permissions": ["machine:read", "risky_command:execute"]},
    )
    _refused(resp, missing=["risky_command:execute"])
    group = (
        await client.get(
            f"/api/v1/groups/{parc['readonly_group']}", headers=parc["tech_headers"]
        )
    ).json()
    assert "risky_command:execute" not in group["permissions"]


async def test_may_edit_a_group_within_reach(client, parc):
    resp = await client.patch(
        f"/api/v1/groups/{parc['readonly_group']}",
        headers=parc["tech_headers"],
        json={"name": "Consultation", "permissions": ["machine:read"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["permissions"] == ["machine:read"]


async def test_cannot_delete_a_group_granting_more_than_one_holds(
    client, parc, db_session
):
    risky = await _group(db_session, "Arrêts", ["risky_command:execute"])
    resp = await client.delete(f"/api/v1/groups/{risky}", headers=parc["tech_headers"])
    _refused(resp, missing=["risky_command:execute"])
    resp = await client.delete(f"/api/v1/groups/{risky}", headers=parc["admin_headers"])
    assert resp.status_code == 204


# --- (b) Placing an account in a group -------------------------------------------


@pytest.mark.parametrize(
    ("group", "admin"), [("admin_group", True), ("technician_group", False)]
)
async def test_cannot_create_an_account_in_a_more_powerful_group(
    client, parc, group, admin
):
    resp = await client.post(
        "/api/v1/users",
        headers=parc["tech_headers"],
        json={
            "email": "complice@test.local",
            "password": STRONG,
            "group_ids": [parc[group]],
        },
    )
    _refused(resp, admin=admin)
    users = (await client.get("/api/v1/users", headers=parc["tech_headers"])).json()
    assert "complice@test.local" not in {u["email"] for u in users["items"]}


async def test_may_create_an_account_in_a_group_within_reach(client, parc):
    resp = await client.post(
        "/api/v1/users",
        headers=parc["tech_headers"],
        json={
            "email": "nouveau@test.local",
            "password": STRONG,
            "group_ids": [parc["readonly_group"], parc["managers_group"]],
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("group", ["admin_group", "technician_group"])
async def test_cannot_move_an_account_into_a_more_powerful_group(client, parc, group):
    resp = await client.patch(
        f"/api/v1/users/{parc['readonly']}",
        headers=parc["tech_headers"],
        json={"group_ids": [parc[group]]},
    )
    _refused(resp)
    user = (
        await client.get(
            f"/api/v1/users/{parc['readonly']}", headers=parc["tech_headers"]
        )
    ).json()
    assert [g["id"] for g in user["groups"]] == [parc["readonly_group"]]


async def test_may_move_an_account_between_groups_within_reach(client, parc):
    resp = await client.patch(
        f"/api/v1/users/{parc['readonly']}",
        headers=parc["tech_headers"],
        json={"group_ids": [parc["managers_group"]]},
    )
    assert resp.status_code == 200, resp.text


async def test_every_permission_still_does_not_make_an_administrator(
    client, parc, db_session
):
    """A composed group granting the whole catalogue is not the administrators'
    group: its members can hand out any permission, never administrator."""
    from app.features.user.permissions import ALL_PERMISSIONS

    everything = await _group(db_session, "Tout", sorted(ALL_PERMISSIONS))
    await _user(db_session, "presque@test.local", [uuid.UUID(everything)])
    headers = await _login(client, "presque@test.local")
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": "admin2@test.local",
            "password": STRONG,
            "group_ids": [parc["admin_group"]],
        },
    )
    _refused(resp, missing=[], admin=True)
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": "technicien2@test.local",
            "password": STRONG,
            "group_ids": [parc["technician_group"]],
        },
    )
    assert resp.status_code == 201, resp.text


# --- (c) Reaching a more powerful account ----------------------------------------


@pytest.mark.parametrize("target", ["admin", "technician"])
async def test_cannot_reach_a_more_powerful_account(client, db_session, parc, target):
    """Edit, deactivate, delete, reset: all four refused, and nothing changed —
    the reset above all, whose answer is the new password in clear."""
    headers = parc["tech_headers"]
    url = f"/api/v1/users/{parc[target]}"
    _refused(await client.patch(url, headers=headers, json={"full_name": "Pirate"}))
    _refused(await client.patch(url, headers=headers, json={"is_active": False}))
    _refused(await client.patch(url, headers=headers, json={"email": "x@test.local"}))
    _refused(await client.delete(url, headers=headers))
    resp = await client.post(f"{url}/reset-password", headers=headers, json={})
    _refused(resp)
    assert "password" not in resp.json()

    user = (await client.get(url, headers=headers)).json()
    assert user["is_active"] and user["full_name"] is None
    email = "admin@test.local" if target == "admin" else "technicien@test.local"
    assert user["email"] == email
    # The account's own password still works: the reset never happened.
    await _login(client, email)


async def test_may_reach_an_account_within_reach(client, parc):
    headers = parc["tech_headers"]
    url = f"/api/v1/users/{parc['readonly']}"
    resp = await client.patch(url, headers=headers, json={"full_name": "Lecteur"})
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"{url}/reset-password", headers=headers, json={})
    assert resp.status_code == 200, resp.text
    await _login(client, "ro@test.local", resp.json()["password"])


async def test_an_administrator_keeps_every_power(client, parc):
    headers = parc["admin_headers"]
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": "admin2@test.local",
            "password": STRONG,
            "group_ids": [parc["admin_group"]],
        },
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        f"/api/v1/users/{parc['technician']}/reset-password", headers=headers, json={}
    )
    assert resp.status_code == 200
    resp = await client.patch(
        f"/api/v1/groups/{parc['technician_group']}",
        headers=headers,
        json={"permissions": ["machine:read"]},
    )
    assert resp.status_code == 200


async def test_a_refusal_is_logged_and_leaves_no_audit_entry(client, parc, caplog):
    with caplog.at_level(logging.WARNING, logger="app.security"):
        resp = await client.post(
            f"/api/v1/users/{parc['admin']}/reset-password",
            headers=parc["tech_headers"],
            json={},
        )
    _refused(resp)
    assert any(
        "privilege escalation refused: tech@test.local" in r.getMessage()
        for r in caplog.records
    )
    audit = (
        await client.get(
            "/api/v1/audit",
            headers=parc["admin_headers"],
            params={"action": "user.reset_password"},
        )
    ).json()
    assert audit["total"] == 0


async def test_the_older_guards_still_apply(client, parc):
    """The rule comes on top of the self-edit guard, it does not replace it: an
    account's own groups stay out of its hands even within its rights."""
    resp = await client.patch(
        f"/api/v1/users/{parc['tech']}",
        headers=parc["tech_headers"],
        json={"group_ids": [parc["readonly_group"]]},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "user.self.forbidden"
