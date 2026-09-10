"""Groups: composed permission sets, the built-in three, the lock-out guard,
and the everyday / risky split on command execution.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid

STRONG = "correct-horse-battery"


async def _login(client, email, password=STRONG):
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _user(client, db_session, email, groups):
    from app.features.user import crud

    await crud.create_user(db_session, email=email, password=STRONG, groups=groups)
    return await _login(client, email)


async def _admin(client, db_session, email="admin@test.local"):
    """An administrator, on a database seeded with the three built-in groups —
    what the migration and the seed script leave behind on a real install."""
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.ensure_builtin_groups(db_session)
    await db_session.commit()
    return await _user(client, db_session, email, [BuiltinGroup.ADMIN])


async def _machine(db_session, hostname="PC-1"):
    from app.features.machine.models import Machine

    m = Machine(machine_uuid=str(uuid.uuid4()), hostname=hostname)
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return m


async def _create_group(client, headers, name, permissions):
    resp = await client.post(
        "/api/v1/groups",
        headers=headers,
        json={"name": name, "permissions": permissions},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _code(resp):
    return resp.json()["error"]["code"]


# --- Listing and the built-in three ----------------------------------------


async def test_builtin_groups_exist_and_admin_holds_everything(client, db_session):
    from app.features.user.permissions import ALL_PERMISSIONS

    headers = await _admin(client, db_session)
    resp = await client.get("/api/v1/groups", headers=headers)
    assert resp.status_code == 200
    groups = {g["builtin_key"]: g for g in resp.json() if g["builtin_key"]}
    assert set(groups) == {"admin", "readonly", "technician"}
    assert groups["admin"]["is_admin"] is True
    assert set(groups["admin"]["permissions"]) == ALL_PERMISSIONS
    assert groups["admin"]["member_count"] == 1
    assert "risky_command:execute" in groups["technician"]["permissions"]
    assert "user:read" not in groups["technician"]["permissions"]


async def test_permission_catalogue_is_served(client, db_session):
    headers = await _admin(client, db_session)
    resp = await client.get("/api/v1/groups/permissions", headers=headers)
    assert resp.status_code == 200
    keys = [p["key"] for p in resp.json()]
    assert "machine:read" in keys and "risky_command:execute" in keys


async def test_readonly_cannot_see_groups(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    headers = await _user(client, db_session, "ro@test.local", [BuiltinGroup.READONLY])
    resp = await client.get("/api/v1/groups", headers=headers)
    assert resp.status_code == 403


# --- Composing a group ----------------------------------------------------


async def test_profile_reports_the_union_of_group_permissions(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin = await _admin(client, db_session)
    ops = await _create_group(client, admin, "Opérateurs", ["command:execute"])
    from app.features.user import crud

    readonly_id = (await crud.builtin_group(db_session, BuiltinGroup.READONLY)).id
    await db_session.commit()
    headers = await _user(
        client, db_session, "ops@test.local", [readonly_id, uuid.UUID(ops["id"])]
    )
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert sorted(g["name"] for g in me["groups"]) == ["Lecture seule", "Opérateurs"]
    assert set(me["permissions"]) == {
        "machine:read",
        "threat:read",
        "command:read",
        "room:read",
        "intervention:read",
        "check:read",
        "command:execute",
    }


async def test_unknown_permission_is_refused(client, db_session):
    admin = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/groups",
        headers=admin,
        json={"name": "Typo", "permissions": ["machine:fly"]},
    )
    assert resp.status_code == 422
    assert _code(resp) == "group.permission.unknown"


async def test_group_name_must_be_unique(client, db_session):
    admin = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/groups", headers=admin, json={"name": "Lecture seule"}
    )
    assert resp.status_code == 409
    assert _code(resp) == "group.name.taken"


async def test_editing_a_group_changes_its_members_rights_at_once(client, db_session):
    admin = await _admin(client, db_session)
    ops = await _create_group(client, admin, "Opérateurs", ["machine:read"])
    headers = await _user(client, db_session, "ops@test.local", [uuid.UUID(ops["id"])])
    assert (await client.get("/api/v1/users", headers=headers)).status_code == 403

    resp = await client.patch(
        f"/api/v1/groups/{ops['id']}",
        headers=admin,
        json={"permissions": ["machine:read", "user:read"], "description": "Accueil"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "Accueil"
    # No new token: the permission set is read on every request.
    assert (await client.get("/api/v1/users", headers=headers)).status_code == 200


async def test_admin_permissions_cannot_be_edited_nor_builtins_deleted(
    client, db_session
):
    admin = await _admin(client, db_session)
    groups = {
        g["builtin_key"]: g
        for g in (await client.get("/api/v1/groups", headers=admin)).json()
    }
    resp = await client.patch(
        f"/api/v1/groups/{groups['admin']['id']}",
        headers=admin,
        json={"permissions": ["machine:read"]},
    )
    assert resp.status_code == 400
    assert _code(resp) == "group.builtin.protected"
    # Renaming a built-in is fine: the key is what the code relies on.
    resp = await client.patch(
        f"/api/v1/groups/{groups['readonly']['id']}",
        headers=admin,
        json={"name": "Consultation"},
    )
    assert resp.status_code == 200
    resp = await client.delete(
        f"/api/v1/groups/{groups['readonly']['id']}", headers=admin
    )
    assert resp.status_code == 400
    assert _code(resp) == "group.builtin.protected"


async def test_deleting_a_group_drops_what_it_granted(client, db_session):
    admin = await _admin(client, db_session)
    ops = await _create_group(client, admin, "Opérateurs", ["machine:read"])
    headers = await _user(client, db_session, "ops@test.local", [uuid.UUID(ops["id"])])
    assert (await client.get("/api/v1/machines", headers=headers)).status_code == 200

    resp = await client.delete(f"/api/v1/groups/{ops['id']}", headers=admin)
    assert resp.status_code == 204
    assert (await client.get("/api/v1/machines", headers=headers)).status_code == 403
    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    assert next(u for u in users if u["email"] == "ops@test.local")["groups"] == []


# --- Lock-out guard ---------------------------------------------------------


async def test_cannot_strip_the_last_account_manager_through_its_group(
    client, db_session
):
    """The only account with user:write holds it through a composed group:
    removing the permission from that group is refused."""
    admin = await _admin(client, db_session)
    managers = await _create_group(
        client, admin, "Gestionnaires", ["user:read", "user:write"]
    )
    manager = await _user(
        client, db_session, "manager@test.local", [uuid.UUID(managers["id"])]
    )
    # The manager demotes the admin: fine, the manager still manages.
    me_admin = (await client.get("/api/v1/auth/me", headers=admin)).json()
    resp = await client.patch(
        f"/api/v1/users/{me_admin['id']}", headers=manager, json={"group_ids": []}
    )
    assert resp.status_code == 200, resp.text

    # Now the manager is the last one: their group may not lose user:write…
    resp = await client.patch(
        f"/api/v1/groups/{managers['id']}",
        headers=manager,
        json={"permissions": ["user:read"]},
    )
    assert resp.status_code == 409
    assert _code(resp) == "user.lockout"
    # …nor be deleted.
    resp = await client.delete(f"/api/v1/groups/{managers['id']}", headers=manager)
    assert resp.status_code == 409
    assert _code(resp) == "user.lockout"
    # And the refused change was rolled back with its audit entry.
    assert (await client.get("/api/v1/users", headers=manager)).status_code == 200


async def test_stripping_user_write_is_fine_while_another_manager_remains(
    client, db_session
):
    admin = await _admin(client, db_session)
    managers = await _create_group(
        client, admin, "Gestionnaires", ["user:read", "user:write"]
    )
    await _user(client, db_session, "manager@test.local", [uuid.UUID(managers["id"])])
    # The admin still manages: the composed group may lose the permission.
    resp = await client.patch(
        f"/api/v1/groups/{managers['id']}",
        headers=admin,
        json={"permissions": ["user:read"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["permissions"] == ["user:read"]


async def test_deactivated_accounts_do_not_count_as_managers(client, db_session):
    """An inactive admin is no safety net: the guard counts active holders."""
    admin = await _admin(client, db_session)
    managers = await _create_group(
        client, admin, "Gestionnaires", ["user:read", "user:write"]
    )
    manager = await _user(
        client, db_session, "manager@test.local", [uuid.UUID(managers["id"])]
    )
    me_admin = (await client.get("/api/v1/auth/me", headers=admin)).json()
    resp = await client.patch(
        f"/api/v1/users/{me_admin['id']}", headers=manager, json={"is_active": False}
    )
    assert resp.status_code == 200, resp.text
    resp = await client.delete(f"/api/v1/groups/{managers['id']}", headers=manager)
    assert resp.status_code == 409
    assert _code(resp) == "user.lockout"


# --- Everyday vs risky commands ---------------------------------------------


async def test_everyday_group_runs_a_scan_but_not_a_reboot(client, db_session):
    admin = await _admin(client, db_session)
    ops = await _create_group(
        client, admin, "Opérateurs", ["machine:read", "command:read", "command:execute"]
    )
    headers = await _user(client, db_session, "ops@test.local", [uuid.UUID(ops["id"])])
    machine = await _machine(db_session)

    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "machine_ids": [str(machine.id)]},
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "reboot", "machine_ids": [str(machine.id)]},
    )
    assert resp.status_code == 403
    body = resp.json()["error"]
    assert body["code"] == "auth.permission.denied"
    assert body["details"] == {"resource": "risky_command", "action": "execute"}


async def test_technician_runs_a_reboot(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    headers = await _user(
        client, db_session, "tech@test.local", [BuiltinGroup.TECHNICIAN]
    )
    machine = await _machine(db_session)
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "shutdown", "machine_ids": [str(machine.id)]},
    )
    assert resp.status_code == 200, resp.text
    # But manages nothing.
    resp = await client.post(
        f"/api/v1/machines/{machine.id}/revoke-token", headers=headers
    )
    assert resp.status_code == 403


async def test_risky_alone_is_not_enough_to_reach_the_route(client, db_session):
    """``risky_command:execute`` without ``command:execute`` opens nothing: the
    route is gated on the everyday permission, the risky one is an addition."""
    admin = await _admin(client, db_session)
    odd = await _create_group(client, admin, "Bizarre", ["risky_command:execute"])
    headers = await _user(client, db_session, "odd@test.local", [uuid.UUID(odd["id"])])
    machine = await _machine(db_session)
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "reboot", "machine_ids": [str(machine.id)]},
    )
    assert resp.status_code == 403
