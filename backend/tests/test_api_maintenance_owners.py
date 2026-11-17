"""Who may own a maintenance, and whether they still can: the default owner's
rule, an owner who stopped qualifying, the merge, and the picker's list.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.features.user.permissions import (
    ALL_PERMISSIONS,
    Action,
    BuiltinGroup,
    Resource,
    permission_key,
)
from app.features.user.scope import Scope
from tests.scope_helpers import SITE_A, SITE_B, account, group, two_sites

OUT_OF_REACH = "maintenance.owner.out_of_reach"


async def _id(db_session, email: str) -> str:
    from app.features.user import crud as user_crud

    user = await user_crud.get_by_email(db_session, email)
    assert user is not None
    return str(user.id)


async def _regroup(db_session, email: str, groups) -> None:
    """Replace an account's groups (ids or built-in keys)."""
    from app.features.user import crud as user_crud

    user = await user_crud.get_by_email(db_session, email)
    assert user is not None
    ids = []
    for g in groups:
        if isinstance(g, BuiltinGroup):
            ids.append((await user_crud.builtin_group(db_session, g)).id)
        else:
            ids.append(g)
    await user_crud.set_user_groups(db_session, user, ids)
    await db_session.commit()


async def _move(db_session, machine_id, **values) -> None:
    from sqlalchemy import update

    from app.features.machine.models import Machine

    await db_session.exec(
        update(Machine).where(Machine.id == machine_id).values(**values)
    )
    await db_session.commit()


async def _overdue(db_session, *machine_ids) -> None:
    for machine_id in machine_ids:
        await _move(
            db_session, machine_id, first_seen=datetime.now(UTC) - timedelta(days=400)
        )


async def _resolved(client, headers, machine_id) -> dict:
    resp = await client.get(
        f"/api/v1/machines/{machine_id}/maintenance", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _due(client, headers, owner: str) -> dict:
    resp = await client.get(
        "/api/v1/maintenance/due", headers=headers, params={"owner": owner}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _due_hostnames(body: dict) -> set[str]:
    names = {m["hostname"] for m in body["machines"]}
    for room in body["rooms"]:
        names |= {m["hostname"] for m in room["machines"]}
    return names


async def _set_default(client, headers, owner_id, **more):
    return await client.patch(
        "/api/v1/settings",
        headers=headers,
        json={"maintenance_default_owner_id": owner_id, **more},
    )


@pytest.fixture
def mail(monkeypatch):
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.test.local")
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-test")


async def _queued(db_session) -> dict[str, str]:
    from sqlmodel import select

    from app.features.notification.models import EmailOutbox

    rows = await db_session.exec(select(EmailOutbox))
    return {row.to_address: row.body for row in rows.all()}


# --- The default owner --------------------------------------------------------


async def test_the_default_owner_must_do_maintenance_over_the_whole_parc(
    client, db_session
):
    """Any poste with no owner of its own falls to the default one: an account
    confined to a site, or one that cannot record a visit, is refused like it
    would be on a poste out of its reach."""
    t = await two_sites(client, db_session)
    await account(client, db_session, "ro@test.local", [BuiltinGroup.READONLY])
    await account(client, db_session, "tech@test.local", [BuiltinGroup.TECHNICIAN])

    for email in ("tech-a@test.local", "ro@test.local"):
        refused = await _set_default(client, t.admin, await _id(db_session, email))
        assert refused.status_code == 422, (email, refused.text)
        assert refused.json()["error"]["code"] == OUT_OF_REACH
    stored = (await client.get("/api/v1/settings", headers=t.admin)).json()
    assert stored["maintenance_default_owner"] is None

    tech_id = await _id(db_session, "tech@test.local")
    ok = await _set_default(client, t.admin, tech_id)
    assert ok.status_code == 200, ok.text
    assert ok.json()["maintenance_default_owner"]["id"] == tech_id


async def test_the_default_owner_is_checked_only_when_it_changes(client, db_session):
    """The card sends every field: the owner already stored, who lost the
    rights since, must not keep the cycle from being saved."""
    t = await two_sites(client, db_session)
    await account(client, db_session, "tech@test.local", [BuiltinGroup.TECHNICIAN])
    tech_id = await _id(db_session, "tech@test.local")
    assert (await _set_default(client, t.admin, tech_id)).status_code == 200
    await _regroup(db_session, "tech@test.local", [BuiltinGroup.READONLY])

    again = await _set_default(
        client, t.admin, tech_id, maintenance_default_cycle_days=45
    )
    assert again.status_code == 200, again.text
    assert again.json()["maintenance_default_cycle_days"] == 45
    # Stored still, but no longer in force: nobody is handed the parc.
    assert again.json()["maintenance_default_owner"] is None
    assert (await _resolved(client, t.admin, t.a.id))["resolved"]["owner"] is None


# --- An owner who stopped qualifying ------------------------------------------


async def test_an_owner_whose_poste_moved_out_of_sight_is_skipped_not_mailed(
    client, db_session, mail
):
    """The poste moved to another site: its owner keeps the stored line, but
    the resolution falls to the next level — the default owner — in the fiche,
    under « Mes tâches » and in the reminder mail, which no longer names a
    hostname the account cannot open."""
    from app.features.machine.models import Machine
    from app.features.notification import tasks
    from app.features.user.models import User

    t = await two_sites(client, db_session)
    tech_a_id = await _id(db_session, "tech-a@test.local")
    admin_id = await _id(db_session, "admin@test.local")
    assert (await _set_default(client, t.admin, admin_id)).status_code == 200
    ok = await client.patch(
        f"/api/v1/machines/{t.a.id}/maintenance",
        headers=t.admin,
        json={"maintenance_owner_id": tech_a_id},
    )
    assert ok.status_code == 200, ok.text
    await _overdue(db_session, t.a.id)
    assert _due_hostnames(await _due(client, t.scoped, "me")) == {"PC-A"}

    await _move(db_session, t.a.id, location=SITE_B)

    fiche = await _resolved(client, t.admin, t.a.id)
    assert fiche["maintenance_owner"]["id"] == tech_a_id  # stored, unchanged
    assert fiche["resolved"]["owner"]["id"] == admin_id
    assert fiche["resolved"]["owner_origin"] == "global"
    assert _due_hostnames(await _due(client, t.scoped, "me")) == set()
    assert "PC-A" in _due_hostnames(await _due(client, t.admin, "me"))

    # The admin on « seulement s'il y a du nouveau »: the reminder is theirs
    # (on the daily digest, the same block would be in the digest instead).
    admin = await db_session.get(User, uuid.UUID(admin_id))
    admin.email_preference = "digest_events"
    db_session.add(admin)
    await db_session.commit()
    assert await tasks.send_maintenance_reminders(db_session) == 1
    queued = await _queued(db_session)
    assert set(queued) == {"admin@test.local"}
    assert "PC-A" in queued["admin@test.local"]

    row = await db_session.get(Machine, t.a.id)
    await db_session.refresh(row)
    assert str(row.maintenance_owner_id) == tech_a_id

    # Back in sight, the owner is the owner again: nothing was rewritten.
    await _move(db_session, t.a.id, location=SITE_A)
    assert _due_hostnames(await _due(client, t.scoped, "me")) == {"PC-A"}


async def test_an_owner_who_lost_the_rights_is_skipped_at_every_level(
    client, db_session, mail
):
    """Rights removed: the room's owner and a poste's own owner both fall
    through, the postes show under « À prendre », and the digest's personal
    block no longer lists them for that account."""
    from app.features.notification import tasks
    from app.features.user import crud as user_crud

    t = await two_sites(client, db_session)
    await account(client, db_session, "tech@test.local", [BuiltinGroup.TECHNICIAN])
    tech_id = await _id(db_session, "tech@test.local")
    resp = await client.post("/api/v1/rooms", headers=t.admin, json={"name": "B12"})
    room_id = resp.json()["id"]
    await _move(db_session, t.b.id, room_id=uuid.UUID(room_id))
    for path in (f"/rooms/{room_id}/maintenance", f"/machines/{t.a.id}/maintenance"):
        ok = await client.patch(
            f"/api/v1{path}", headers=t.admin, json={"maintenance_owner_id": tech_id}
        )
        assert ok.status_code == 200, ok.text
    await _overdue(db_session, t.a.id, t.b.id)
    tech = await account_headers(client, "tech@test.local")
    assert _due_hostnames(await _due(client, tech, "me")) == {"PC-A", "PC-B"}

    await _regroup(db_session, "tech@test.local", [BuiltinGroup.READONLY])

    room = (
        await client.get(f"/api/v1/rooms/{room_id}/maintenance", headers=t.admin)
    ).json()
    assert room["maintenance_owner"]["id"] == tech_id
    assert room["effective_owner"] is None
    listed = (await client.get("/api/v1/rooms", headers=t.admin)).json()
    assert [r["effective_owner_name"] for r in listed if r["id"] == room_id] == [None]
    for machine in (t.a, t.b):
        assert (await _resolved(client, t.admin, machine.id))["resolved"][
            "owner"
        ] is None
    assert _due_hostnames(await _due(client, t.admin, tech_id)) == set()
    assert _due_hostnames(await _due(client, t.admin, "none")) == {"PC-A", "PC-B"}

    user = await user_crud.get_by_email(db_session, "tech@test.local")
    assert await tasks.personal_block(db_session, user) == []
    assert await tasks.send_maintenance_reminders(db_session) == 0


async def account_headers(client, email: str) -> dict:
    from tests.scope_helpers import login

    return await login(client, email)


async def test_resolving_owners_costs_the_same_whatever_the_parc(
    client, db_session, engine
):
    """The due list resolves an owner per poste: the accounts' rights and
    scopes are read once for all of them, so neither more postes nor more
    owners add a statement."""
    from sqlalchemy import event

    from app.features.machine.models import Machine

    t = await two_sites(client, db_session)
    tech_a_id = await _id(db_session, "tech-a@test.local")
    await client.patch(
        f"/api/v1/machines/{t.a.id}/maintenance",
        headers=t.admin,
        json={"maintenance_owner_id": tech_a_id},
    )

    statements: list[str] = []

    def count(_conn, _cursor, statement, *_rest):
        statements.append(statement)

    async def cost() -> int:
        statements.clear()
        await _due(client, t.admin, "none")
        return len(statements)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        small = await cost()
        # Twelve more postes, each with a confined owner of its own.
        from app.features.user import crud as user_crud

        for n in range(12):
            site = f"Site {n}"
            g = await group(
                db_session,
                f"Tech {n}",
                ALL_PERMISSIONS,
                Scope(locations=frozenset({site})),
            )
            owner = await user_crud.create_user(
                db_session,
                email=f"tech-{n}@test.local",
                password="correct-horse-battery",
                groups=[g.id],
            )
            owner_id = owner.id
            db_session.add(
                Machine(
                    machine_uuid=str(uuid.uuid4()),
                    hostname=f"PC-{n}",
                    # Half of them moved away from their owner since.
                    location=site if n % 2 else SITE_B,
                    maintenance_owner_id=owner_id,
                )
            )
        await db_session.commit()
        large = await cost()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)
    assert large == small, (small, large)
    # And the answer is the rule's: the six that moved are to be taken.
    unowned = _due_hostnames(await _due(client, t.admin, "none"))
    assert {f"PC-{n}" for n in range(0, 12, 2)} <= unowned
    assert not {f"PC-{n}" for n in range(1, 12, 2)} & unowned


async def test_the_scope_matched_in_python_is_the_sql_clause(client, db_session):
    """The resolution matches a scope in memory; the routes filter with
    ``machine_clause`` and ``room_clause``. Same answer, row by row."""
    from sqlmodel import col, select

    from app.features.machine.models import Machine
    from app.features.room.models import Building, Room
    from app.features.user import scope as scope_rules

    b1 = Building(name="Bât 1", location=SITE_A)
    b2 = Building(name="Bât 2")
    db_session.add_all([b1, b2])
    await db_session.flush()
    rooms = [
        Room(name="R1", building_id=b1.id),
        # The building's site wins over the room's own.
        Room(name="R2", building_id=b1.id, location=SITE_B),
        Room(name="R3", building_id=b2.id, location=SITE_B),
        Room(name="R4", building_id=b2.id),
        Room(name="R5", location=SITE_A),
        Room(name="R6"),
    ]
    db_session.add_all(rooms)
    await db_session.flush()
    room_ids = [r.id for r in rooms]
    building_ids = [b1.id, b2.id]
    machines = []
    for n, room_id in enumerate([*room_ids, None]):
        for location in (None, SITE_A, SITE_B, "Ailleurs"):
            machines.append(
                Machine(
                    machine_uuid=f"m-{n}-{location}",
                    location=location,
                    room_id=room_id,
                )
            )
    db_session.add_all(machines)
    await db_session.commit()

    scopes = [
        None,
        Scope(),
        Scope(locations=frozenset({SITE_A})),
        Scope(locations=frozenset({SITE_B, "Nulle part"})),
        Scope(buildings=frozenset({building_ids[1]})),
        Scope(rooms=frozenset({room_ids[5], room_ids[0], uuid.uuid4()})),
        Scope(
            locations=frozenset({SITE_B}),
            buildings=frozenset({building_ids[0]}),
            rooms=frozenset({room_ids[4]}),
        ),
    ]
    places = await scope_rules.room_places(db_session)
    all_machines = (await db_session.exec(select(Machine))).all()
    differing = set()
    for scope in scopes:
        clause = scope_rules.machine_clause(scope)
        stmt = select(col(Machine.id))
        in_sql = set((await db_session.exec(scope_rules.restrict(stmt, clause))).all())
        in_python = {
            m.id
            for m in all_machines
            if scope_rules.machine_in_scope(
                scope, location=m.location, room_id=m.room_id, places=places
            )
        }
        assert in_python == in_sql, scope
        differing.add(len(in_sql))

        room_stmt = scope_rules.restrict(
            select(col(Room.id)), scope_rules.room_clause(scope)
        )
        rooms_sql = set((await db_session.exec(room_stmt)).all())
        rooms_python = {
            rid for rid in room_ids if scope_rules.room_in_scope(scope, rid, places)
        }
        assert rooms_python == rooms_sql, scope
    # The scopes tell the rows apart: everything, nothing, and several in between.
    assert len(differing) >= 5 and 0 in differing and len(all_machines) in differing
    # A room deleted since is in no scope.
    assert not scope_rules.room_in_scope(scopes[2], uuid.uuid4(), places)


# --- The merge ----------------------------------------------------------------


@pytest.mark.parametrize("kept_site,copied", [(SITE_A, True), (SITE_B, False)])
async def test_a_merge_copies_the_owner_only_onto_a_poste_they_reach(
    client, db_session, kept_site, copied
):
    from app.features.machine import crud as machine_crud
    from app.features.machine.models import Machine
    from tests.scope_helpers import machine

    t = await two_sites(client, db_session)
    tech_a_id = uuid.UUID(await _id(db_session, "tech-a@test.local"))
    kept = await machine(db_session, "PC-KEPT", location=kept_site)
    await _move(
        db_session, t.a.id, maintenance_owner_id=tech_a_id, maintenance_cycle_days=30
    )

    target = await db_session.get(Machine, kept.id)
    source = await db_session.get(Machine, t.a.id)
    await machine_crud.merge_into(db_session, target=target, source=source)
    await db_session.commit()
    await db_session.refresh(target)

    assert target.maintenance_cycle_days == 30
    assert target.maintenance_owner_id == (tech_a_id if copied else None)


async def test_a_merge_keeps_the_owner_the_kept_poste_already_has(client, db_session):
    from app.features.machine import crud as machine_crud
    from app.features.machine.models import Machine

    t = await two_sites(client, db_session)
    tech_a_id = uuid.UUID(await _id(db_session, "tech-a@test.local"))
    admin_id = uuid.UUID(await _id(db_session, "admin@test.local"))
    await _move(db_session, t.a.id, maintenance_owner_id=tech_a_id)
    await _move(db_session, t.b.id, maintenance_owner_id=admin_id)
    target = await db_session.get(Machine, t.b.id)
    source = await db_session.get(Machine, t.a.id)
    await machine_crud.merge_into(db_session, target=target, source=source)
    await db_session.commit()
    await db_session.refresh(target)
    assert target.maintenance_owner_id == admin_id


# --- The picker ---------------------------------------------------------------


async def _owners(client, headers, **params):
    return await client.get(
        "/api/v1/maintenance/assignable-owners", headers=headers, params=params
    )


async def _picker_parc(client, db_session):
    """Two sites, a room on each, and one account of each kind."""
    t = await two_sites(client, db_session)
    await account(client, db_session, "ro@test.local", [BuiltinGroup.READONLY])
    await account(client, db_session, "tech@test.local", [BuiltinGroup.TECHNICIAN])
    await account(client, db_session, "gone@test.local", [BuiltinGroup.TECHNICIAN])
    from app.features.user import crud as user_crud

    gone = await user_crud.get_by_email(db_session, "gone@test.local")
    gone.is_active = False
    db_session.add(gone)
    await db_session.commit()
    rooms = {}
    for name, site in (("Salle A", SITE_A), ("Salle B", SITE_B)):
        resp = await client.post(
            "/api/v1/rooms", headers=t.admin, json={"name": name, "location": site}
        )
        assert resp.status_code == 201, resp.text
        rooms[site] = resp.json()["id"]
    return t, rooms


async def test_the_picker_offers_exactly_who_the_server_accepts(client, db_session):
    t, rooms = await _picker_parc(client, db_session)
    ids = {
        email: await _id(db_session, f"{email}@test.local")
        for email in ("admin", "tech", "tech-a", "ro", "gone")
    }

    def offered(resp) -> set[str]:
        assert resp.status_code == 200, resp.text
        by_id = {v: k for k, v in ids.items()}
        assert all(set(item) == {"id", "name"} for item in resp.json())
        return {by_id[item["id"]] for item in resp.json()}

    # Neither: the candidates for the parc's default owner.
    assert offered(await _owners(client, t.admin)) == {"admin", "tech"}
    assert offered(await _owners(client, t.admin, machine_id=str(t.a.id))) == {
        "admin",
        "tech",
        "tech-a",
    }
    assert offered(await _owners(client, t.admin, machine_id=str(t.b.id))) == {
        "admin",
        "tech",
    }
    assert offered(await _owners(client, t.admin, room_id=rooms[SITE_A])) == {
        "admin",
        "tech",
        "tech-a",
    }
    assert offered(await _owners(client, t.admin, room_id=rooms[SITE_B])) == {
        "admin",
        "tech",
    }

    # The list the console used before offers accounts the write refuses;
    # this one offers none of them, and every one it offers is accepted.
    before = await client.get("/api/v1/checks/assignable-users", headers=t.admin)
    # (It no longer offers read-only accounts, which cannot close a check;
    # an account confined to the other site is still there.)
    assert ids["tech-a"] in {u["id"] for u in before.json()}
    assert ids["ro"] not in {u["id"] for u in before.json()}
    for name, account_id in ids.items():
        resp = await client.patch(
            f"/api/v1/machines/{t.b.id}/maintenance",
            headers=t.admin,
            json={"maintenance_owner_id": account_id},
        )
        accepted = name in {"admin", "tech"}
        assert (resp.status_code == 200) is accepted, (name, resp.text)


async def test_the_picker_applies_the_callers_own_scope(client, db_session):
    t, rooms = await _picker_parc(client, db_session)

    mine = await _owners(client, t.scoped, machine_id=str(t.a.id))
    assert mine.status_code == 200, mine.text
    assert (await _owners(client, t.scoped, room_id=rooms[SITE_A])).status_code == 200

    hidden = await _owners(client, t.scoped, machine_id=str(t.b.id))
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "machine.not_found"
    hidden_room = await _owners(client, t.scoped, room_id=rooms[SITE_B])
    assert hidden_room.status_code == 404
    assert hidden_room.json()["error"]["code"] == "room.not_found"
    unknown = await _owners(client, t.admin, machine_id=str(uuid.uuid4()))
    assert unknown.status_code == 404

    both = await _owners(client, t.admin, machine_id=str(t.a.id), room_id=rooms[SITE_A])
    assert both.status_code == 422


async def test_the_picker_is_for_who_sets_an_owner(client, db_session):
    """maintenance:write (a poste, a room) or settings:write (the default) —
    not maintenance:read alone, and not behind it either: the settings page
    is opened by accounts that never read a maintenance list."""
    t, _rooms = await _picker_parc(client, db_session)
    readonly = await account_headers(client, "ro@test.local")
    assert (await _owners(client, readonly)).status_code == 403

    settings_only = await group(
        db_session,
        "Paramètres",
        {
            permission_key(Resource.SETTINGS, Action.READ),
            permission_key(Resource.SETTINGS, Action.WRITE),
        },
        None,
    )
    config = await account(client, db_session, "config@test.local", [settings_only.id])
    resp = await _owners(client, config)
    assert resp.status_code == 200, resp.text
    assert {u["name"] for u in resp.json()} == {"admin@test.local", "tech@test.local"}

    tech = await account_headers(client, "tech@test.local")
    assert (await _owners(client, tech, machine_id=str(t.a.id))).status_code == 200
