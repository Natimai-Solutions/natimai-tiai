"""Groups restricted to sites, buildings or rooms (``user/scope.py``).

The pattern throughout: two sites with one poste each, an account confined to
the first. What lies on the second site must be absent from every list and
aggregate, and answer 404 when named — as if it did not exist.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid
from types import SimpleNamespace

from app.features.user.scope import Scope, union, wider
from tests.scope_helpers import (
    SITE_A,
    SITE_B,
    account,
    group,
    machine,
    two_sites,
)

# --- pure rules ---------------------------------------------------------------


def test_an_unrestricted_group_lifts_the_restriction():
    a = Scope(locations=frozenset({SITE_A}))
    assert union([a, None]) is None
    assert union([a, Scope(locations=frozenset({SITE_B}))]) == Scope(
        locations=frozenset({SITE_A, SITE_B})
    )


def test_no_group_at_all_confines_to_nothing():
    assert union([]) == Scope()


def test_wider_is_the_escalation_half():
    a = Scope(locations=frozenset({SITE_A}))
    ab = Scope(locations=frozenset({SITE_A, SITE_B}))
    assert not wider(None, a)  # the unrestricted reach everything
    assert wider(a, None)  # "the whole parc" is beyond a site
    assert wider(a, ab)
    assert not wider(ab, a)


def test_malformed_ids_are_dropped_not_widened():
    scope = Scope.from_rows([("room", "not-a-uuid"), ("location", SITE_A)])
    assert scope == Scope(locations=frozenset({SITE_A}))


# --- machines -----------------------------------------------------------------


async def test_the_list_and_its_facets_are_narrowed(client, db_session):
    t = await two_sites(client, db_session)

    mine = await client.get("/api/v1/machines", headers=t.scoped)
    assert mine.status_code == 200
    assert [m["hostname"] for m in mine.json()["items"]] == ["PC-A"]
    assert mine.json()["total"] == 1

    everyone = await client.get("/api/v1/machines", headers=t.admin)
    assert everyone.json()["total"] == 2

    # The facet listings would otherwise name the other site.
    locations = await client.get("/api/v1/machines/locations", headers=t.scoped)
    assert [v["name"] for v in locations.json()] == [SITE_A]


async def test_a_machine_out_of_scope_is_not_found(client, db_session):
    t = await two_sites(client, db_session)

    assert (
        await client.get(f"/api/v1/machines/{t.a.id}", headers=t.scoped)
    ).status_code == 200
    resp = await client.get(f"/api/v1/machines/{t.b.id}", headers=t.scoped)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "machine.not_found"
    # Same answer for its other faces.
    for path in ("usage", "duplicates", "interventions", "checks", "maintenance"):
        r = await client.get(f"/api/v1/machines/{t.b.id}/{path}", headers=t.scoped)
        assert r.status_code == 404, path


async def test_the_export_is_narrowed(client, db_session):
    t = await two_sites(client, db_session)
    resp = await client.get("/api/v1/machines/export.csv", headers=t.scoped)
    assert resp.status_code == 200
    assert "PC-A" in resp.text and "PC-B" not in resp.text


async def test_a_room_on_the_site_counts_even_without_the_agents_word(
    client, db_session
):
    """A poste whose agent reports no site is on site A if its room is."""
    from app.features.room.models import Building, Room

    t = await two_sites(client, db_session)
    building = Building(name="Bât. C", location=SITE_A)
    db_session.add(building)
    await db_session.flush()
    room = Room(name="C12", building_id=building.id)
    db_session.add(room)
    await db_session.flush()
    room_id = room.id
    await db_session.commit()
    await machine(db_session, "PC-ROOM", room_id=room_id)

    resp = await client.get("/api/v1/machines", headers=t.scoped)
    assert sorted(m["hostname"] for m in resp.json()["items"]) == ["PC-A", "PC-ROOM"]


async def test_a_room_scope_sees_that_room_alone(client, db_session):
    from app.features.room.models import Building, Room

    building = Building(name="Bât. D", location=SITE_A)
    db_session.add(building)
    await db_session.flush()
    d1 = Room(name="D1", building_id=building.id)
    d2 = Room(name="D2", building_id=building.id)
    db_session.add_all([d1, d2])
    await db_session.flush()
    d1_id, d2_id = d1.id, d2.id
    await db_session.commit()
    await machine(db_session, "PC-D1", location=SITE_A, room_id=d1_id)
    await machine(db_session, "PC-D2", location=SITE_A, room_id=d2_id)
    g = await group(
        db_session,
        "Salle D1",
        {"machine:read", "room:read"},
        Scope(rooms=frozenset({d1_id})),
    )
    headers = await account(client, db_session, "d1@test.local", [g.id])

    machines = await client.get("/api/v1/machines", headers=headers)
    assert [m["hostname"] for m in machines.json()["items"]] == ["PC-D1"]
    rooms = await client.get("/api/v1/rooms", headers=headers)
    assert [r["name"] for r in rooms.json()] == ["D1"]
    # Its building is named, so the room can be placed on the page…
    buildings = await client.get("/api/v1/buildings", headers=headers)
    assert [b["name"] for b in buildings.json()] == ["Bât. D"]
    # …and the other room of it stays out of reach.
    assert (
        await client.get(f"/api/v1/rooms/{d2_id}", headers=headers)
    ).status_code == 404


async def test_one_unrestricted_group_opens_everything(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    await machine(db_session, "PC-A", location=SITE_A)
    await machine(db_session, "PC-B", location=SITE_B)
    g = await group(
        db_session, "Site A", {"machine:read"}, Scope(locations=frozenset({SITE_A}))
    )
    headers = await account(
        client, db_session, "both@test.local", [g.id, BuiltinGroup.READONLY]
    )
    resp = await client.get("/api/v1/machines", headers=headers)
    assert resp.json()["total"] == 2


# --- commands, threats, dashboard, software -------------------------------------


async def test_a_broadcast_stays_on_the_site(client, db_session):
    from sqlmodel import select

    from app.features.command.models import Command

    t = await two_sites(client, db_session)
    resp = await client.post(
        "/api/v1/commands",
        headers=t.scoped,
        json={"type": "quick_scan", "target_all": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 1
    # A listed poste of the other site is dropped like an unknown id.
    resp = await client.post(
        "/api/v1/commands",
        headers=t.scoped,
        json={"type": "flush_dns", "machine_ids": [str(t.b.id)]},
    )
    assert resp.json()["count"] == 0
    rows = (await db_session.exec(select(Command))).all()
    assert {c.machine_id for c in rows} == {t.a.id}

    listed = await client.get("/api/v1/commands", headers=t.scoped)
    assert listed.json()["total"] == 1


async def test_threats_and_dashboard_are_the_sites(client, db_session):
    from app.features.threat.models import Threat

    t = await two_sites(client, db_session)
    db_session.add_all(
        [
            Threat(machine_id=t.a.id, detection_id="a", status="active"),
            Threat(machine_id=t.b.id, detection_id="b", status="active"),
        ]
    )
    await db_session.commit()

    threats = await client.get("/api/v1/threats", headers=t.scoped)
    assert threats.json()["total"] == 1
    stats = (await client.get("/api/v1/stats/overview", headers=t.scoped)).json()
    assert stats["total"] == 1
    assert stats["with_active_threats"] == 1
    admin_stats = (await client.get("/api/v1/stats/overview", headers=t.admin)).json()
    assert admin_stats["total"] == 2
    assert admin_stats["with_active_threats"] == 2


async def test_the_software_catalogue_counts_the_site(client, db_session):
    from app.features.inventory.models import MachineSoftware, Software

    t = await two_sites(client, db_session)
    shared = Software(name="Firefox", version="1", publisher="Mozilla")
    only_b = Software(name="Outil B", version="1", publisher="")
    db_session.add_all([shared, only_b])
    await db_session.flush()
    shared_id, only_b_id = shared.id, only_b.id
    db_session.add_all(
        [
            MachineSoftware(machine_id=t.a.id, software_id=shared_id),
            MachineSoftware(machine_id=t.b.id, software_id=shared_id),
            MachineSoftware(machine_id=t.b.id, software_id=only_b_id),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/software", headers=t.scoped)
    assert [(s["name"], s["machine_count"]) for s in resp.json()["items"]] == [
        ("Firefox", 1)
    ]


# --- verifications, interventions, maintenance ---------------------------------


async def test_checks_and_interventions_follow_their_poste(client, db_session):
    t = await two_sites(client, db_session)
    for m in (t.a, t.b):
        r = await client.post(
            f"/api/v1/machines/{m.id}/check", headers=t.admin, json={}
        )
        assert r.status_code == 201, r.text
    checks = await client.get("/api/v1/checks", headers=t.scoped)
    assert checks.json()["total"] == 1
    other = [
        c
        for c in (await client.get("/api/v1/checks", headers=t.admin)).json()["items"]
        if c["machine_id"] == str(t.b.id)
    ][0]
    r = await client.get(f"/api/v1/checks/{other['id']}", headers=t.scoped)
    assert r.status_code == 404

    r = await client.post(
        f"/api/v1/machines/{t.b.id}/interventions",
        headers=t.scoped,
        json={"kind": "other", "note": "x"},
    )
    assert r.status_code == 404


async def test_a_visit_across_two_sites_shows_only_the_sites_postes(client, db_session):
    """Audit S06: a visit is visible through one poste of the site, but the
    postes of the other site stay out of its detail and its count."""
    t = await two_sites(client, db_session)
    r = await client.post(
        "/api/v1/maintenance",
        headers=t.admin,
        json={
            "items": [
                {"machine_id": str(t.a.id), "note": "ok"},
                {"machine_id": str(t.b.id), "note": "secret B"},
            ]
        },
    )
    assert r.status_code == 201, r.text
    visit_id = r.json()["id"]
    assert r.json()["machine_count"] == 2

    detail = await client.get(f"/api/v1/maintenance/{visit_id}", headers=t.scoped)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert [i["machine_id"] for i in body["items"]] == [str(t.a.id)]
    assert body["machine_count"] == 1
    assert "secret B" not in detail.text

    listed = await client.get("/api/v1/maintenance", headers=t.scoped)
    assert [v["machine_count"] for v in listed.json()["items"]] == [1]

    full = await client.get(f"/api/v1/maintenance/{visit_id}", headers=t.admin)
    assert len(full.json()["items"]) == 2


async def test_the_due_list_is_the_sites(client, db_session):
    t = await two_sites(client, db_session)

    def names(body):
        return sorted(m["hostname"] for m in body["machines"])

    everyone = (await client.get("/api/v1/maintenance/due", headers=t.admin)).json()
    mine = (await client.get("/api/v1/maintenance/due", headers=t.scoped)).json()
    assert "PC-B" not in names(mine)
    # Not vacuous: the same list read without a scope does carry PC-B.
    assert names(everyone) == sorted([*names(mine), "PC-B"])


# --- rooms and buildings: writes ---------------------------------------------------


async def test_a_confined_account_builds_on_its_site_only(client, db_session):
    t = await two_sites(client, db_session)
    ok = await client.post(
        "/api/v1/buildings", headers=t.scoped, json={"name": "Neuf", "location": SITE_A}
    )
    assert ok.status_code == 201, ok.text
    refused = await client.post(
        "/api/v1/buildings", headers=t.scoped, json={"name": "Neuf", "location": SITE_B}
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "auth.scope.restricted"
    # A room nowhere is nobody's site: refused as well.
    loose = await client.post("/api/v1/rooms", headers=t.scoped, json={"name": "X"})
    assert loose.status_code == 403
    # Moving a building off the site is leaving it.
    moved = await client.patch(
        f"/api/v1/buildings/{ok.json()['id']}",
        headers=t.scoped,
        json={"location": SITE_B},
    )
    assert moved.status_code == 403


async def test_directory_sync_is_for_the_unrestricted(client, db_session):
    t = await two_sites(client, db_session)
    resp = await client.post("/api/v1/rooms/sync-directory", headers=t.scoped)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "auth.scope.restricted"


# --- groups API and escalation -------------------------------------------------------


async def test_a_group_carries_its_scope(client, db_session):
    t = await two_sites(client, db_session)
    resp = await client.post(
        "/api/v1/groups",
        headers=t.admin,
        json={
            "name": "Taravao",
            "permissions": ["machine:read"],
            "scope": {"locations": [SITE_A]},
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["scope"] == {"locations": [SITE_A], "buildings": [], "rooms": []}

    lifted = await client.patch(
        f"/api/v1/groups/{body['id']}", headers=t.admin, json={"scope": None}
    )
    assert lifted.json()["scope"] is None

    unknown = await client.post(
        "/api/v1/groups",
        headers=t.admin,
        json={"name": "Fantôme", "scope": {"rooms": [str(uuid.uuid4())]}},
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "group.scope.unknown"


async def test_a_confined_manager_cannot_widen_anyone(client, db_session):
    """The escape a scope would otherwise have: a confined account holding
    ``user:write`` composes an unrestricted group and joins it."""
    t = await two_sites(client, db_session)

    unrestricted = await client.post(
        "/api/v1/groups",
        headers=t.scoped,
        json={"name": "Partout", "permissions": ["machine:read"]},
    )
    assert unrestricted.status_code == 403
    assert unrestricted.json()["error"]["code"] == "auth.permission.escalation"
    assert unrestricted.json()["error"]["details"]["wider_scope"] is True

    other_site = await client.post(
        "/api/v1/groups",
        headers=t.scoped,
        json={"name": "Site B", "scope": {"locations": [SITE_B]}},
    )
    assert other_site.status_code == 403

    same_site = await client.post(
        "/api/v1/groups",
        headers=t.scoped,
        json={
            "name": "Lecture A",
            "permissions": ["machine:read"],
            "scope": {"locations": [SITE_A]},
        },
    )
    assert same_site.status_code == 201, same_site.text

    # Nor can it lift the scope of a group it can edit.
    lifted = await client.patch(
        f"/api/v1/groups/{same_site.json()['id']}",
        headers=t.scoped,
        json={"scope": None},
    )
    assert lifted.status_code == 403


async def test_a_confined_manager_cannot_widen_a_member_through_a_group(
    client, db_session
):
    """Audit S05: the group stays on site A, but one of its members is also in
    an unrestricted group — what is added here would reach the whole parc."""
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    t = await two_sites(
        client,
        db_session,
        permissions=["user:read", "user:write", "machine:read", "command:execute"],
    )
    tech = await group(
        db_session, "Tech A", ["machine:read"], Scope(locations=frozenset({SITE_A}))
    )
    await account(client, db_session, "m@test.local", [tech.id, BuiltinGroup.READONLY])

    resp = await client.patch(
        f"/api/v1/groups/{tech.id}",
        headers=t.scoped,
        json={"permissions": ["machine:read", "command:execute"]},
    )
    assert resp.status_code == 403, resp.text
    err = resp.json()["error"]
    assert err["code"] == "auth.permission.escalation"
    assert err["details"]["action"] == "edit_members"
    assert err["details"]["wider_scope"] is True
    m = await crud.get_by_email(db_session, "m@test.local")
    assert "command:execute" not in await crud.user_permissions(db_session, m.id)

    # Renaming is no grant: still allowed.
    renamed = await client.patch(
        f"/api/v1/groups/{tech.id}", headers=t.scoped, json={"name": "Tech A bis"}
    )
    assert renamed.status_code == 200, renamed.text

    # A group whose members all sit within the caller's reach: allowed.
    alone = await group(
        db_session,
        "Tech A seuls",
        ["machine:read"],
        Scope(locations=frozenset({SITE_A})),
    )
    await account(client, db_session, "n@test.local", [alone.id])
    ok = await client.patch(
        f"/api/v1/groups/{alone.id}",
        headers=t.scoped,
        json={"permissions": ["machine:read", "command:execute"]},
    )
    assert ok.status_code == 200, ok.text

    # The administrator is not held back.
    admin = await client.patch(
        f"/api/v1/groups/{tech.id}",
        headers=t.admin,
        json={"permissions": ["machine:read", "command:execute"]},
    )
    assert admin.status_code == 200, admin.text


# --- e-mail ------------------------------------------------------------------------------


async def test_the_digest_is_built_for_the_scope(db_session):
    from app.features.notification.digest import build_digest

    await machine(db_session, "PC-A", location=SITE_A)
    await machine(db_session, "PC-B", location=SITE_B)

    assert (await build_digest(db_session)).total == 2
    scoped = await build_digest(db_session, Scope(locations=frozenset({SITE_A})))
    assert scoped.total == 1


async def test_a_threat_alert_goes_to_who_can_see_the_poste(db_session, monkeypatch):
    from app.features.notification import threat_alert
    from app.features.threat.crud import NewDetection
    from app.features.user import crud
    from app.features.user.models import EmailPreference

    b = await machine(db_session, "PC-B", location=SITE_B)
    g = await group(
        db_session, "Site A", {"machine:read"}, Scope(locations=frozenset({SITE_A}))
    )
    for email, groups in (("a@x.fr", [g.id]), ("all@x.fr", None)):
        kwargs = {"groups": groups} if groups else {}
        user = await crud.create_user(db_session, email=email, password="pw", **kwargs)
        user.email_preference = EmailPreference.IMMEDIATE
        db_session.add(user)
    await db_session.commit()

    sent: list[str] = []

    async def enabled(_session):
        return SimpleNamespace(enabled=True)

    def capture(_session, *, to, subject, text):
        sent.append(to)
        return True

    monkeypatch.setattr(threat_alert, "email_policy", enabled)
    monkeypatch.setattr(threat_alert, "queue_email", capture)
    context = threat_alert.MachineContext(
        id=b.id,
        machine_uuid=b.machine_uuid,
        hostname="PC-B",
        domain=None,
        ip_address=None,
        session_username=None,
    )
    detection = NewDetection(
        detection_id="d",
        threat_name="EICAR",
        severity="high",
        status="active",
        detected_at=None,
    )
    assert await threat_alert.queue_threat_alert(db_session, context, [detection]) == 1
    assert sent == ["all@x.fr"]


# --- audit T32 ------------------------------------------------------------------


async def test_a_confined_account_cannot_move_a_place_to_another_site(
    client, db_session
):
    """Audit S16: held by id, a building or a room still stays on its site."""
    t = await two_sites(client, db_session)
    b = await client.post(
        "/api/v1/buildings", headers=t.admin, json={"name": "Bât", "location": SITE_A}
    )
    assert b.status_code == 201, b.text
    held = await group(
        db_session,
        "Bât seul",
        ["room:read", "room:write", "machine:read"],
        Scope(buildings=frozenset({uuid.UUID(b.json()["id"])})),
    )
    tech = await account(client, db_session, "bat@test.local", [held.id])
    moved = await client.patch(
        f"/api/v1/buildings/{b.json()['id']}", headers=tech, json={"location": SITE_B}
    )
    assert moved.status_code == 403, moved.text
    assert moved.json()["error"]["code"] == "auth.scope.restricted"
    renamed = await client.patch(
        f"/api/v1/buildings/{b.json()['id']}", headers=tech, json={"name": "Bât 2"}
    )
    assert renamed.status_code == 200, renamed.text

    room = await client.post(
        "/api/v1/rooms", headers=t.admin, json={"name": "R1", "location": SITE_A}
    )
    by_room = await group(
        db_session,
        "Salle seule",
        ["room:read", "room:write", "machine:read"],
        Scope(rooms=frozenset({uuid.UUID(room.json()["id"])})),
    )
    tech2 = await account(client, db_session, "salle@test.local", [by_room.id])
    out = await client.patch(
        f"/api/v1/rooms/{room.json()['id']}", headers=tech2, json={"location": SITE_B}
    )
    assert out.status_code == 403, out.text
    # The unrestricted may.
    ok = await client.patch(
        f"/api/v1/rooms/{room.json()['id']}", headers=t.admin, json={"location": SITE_B}
    )
    assert ok.status_code == 200, ok.text


async def test_the_audit_log_is_the_sites(client, db_session):
    """Audit S17: entries about postes elsewhere, and the parc's administration,
    stay out of a confined reader's log; its own actions do not."""
    t = await two_sites(client, db_session)
    for m in (t.a, t.b):
        r = await client.post(f"/api/v1/machines/{m.id}/revoke-token", headers=t.admin)
        assert r.status_code in (200, 204), r.text
    own = await client.post(
        f"/api/v1/machines/{t.a.id}/allow-reenroll", headers=t.scoped
    )
    assert own.status_code in (200, 204), own.text
    mine = (await client.get("/api/v1/audit", headers=t.scoped)).json()["items"]
    ids = {e["resource_id"] for e in mine}
    assert str(t.a.id) in ids and str(t.b.id) not in ids
    assert all(
        e["resource_type"] == "machine" or e["actor"] == "tech-a@test.local"
        for e in mine
    )
    everything = (await client.get("/api/v1/audit", headers=t.admin)).json()["items"]
    assert str(t.b.id) in {e["resource_id"] for e in everything}


async def test_a_check_goes_only_to_who_sees_the_poste(client, db_session):
    """Audit S18: the assignee must read checks and see the poste."""
    t = await two_sites(client, db_session)
    from app.features.user import crud as user_crud

    tech_a = await user_crud.get_by_email(db_session, "tech-a@test.local")
    assert tech_a is not None
    tech_a_id = str(tech_a.id)

    refused = await client.post(
        f"/api/v1/machines/{t.b.id}/check",
        headers=t.admin,
        json={"assigned_to_id": tech_a_id},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "check.assignee.out_of_reach"
    bulk = await client.post(
        "/api/v1/checks/bulk",
        headers=t.admin,
        json={"machine_ids": [str(t.a.id), str(t.b.id)], "assigned_to_id": tech_a_id},
    )
    assert bulk.status_code == 422, bulk.text
    ok = await client.post(
        f"/api/v1/machines/{t.a.id}/check",
        headers=t.admin,
        json={"assigned_to_id": tech_a_id},
    )
    assert ok.status_code == 201, ok.text

    for_b = await client.get(
        "/api/v1/checks/assignable-users",
        headers=t.admin,
        params={"machine_id": str(t.b.id)},
    )
    assert tech_a_id not in {u["id"] for u in for_b.json()}
    for_a = await client.get(
        "/api/v1/checks/assignable-users",
        headers=t.admin,
        params={"machine_id": str(t.a.id)},
    )
    assert tech_a_id in {u["id"] for u in for_a.json()}


async def test_a_maintenance_goes_only_to_who_sees_and_does_it(client, db_session):
    """Audit S18 class (T32): a poste's or a room's maintenance owner must
    read and record maintenance and see the poste (the room); checked when
    the owner changes, not when the same one is sent again."""
    from app.features.user import crud as user_crud
    from app.features.user.permissions import BuiltinGroup
    from tests.scope_helpers import account

    t = await two_sites(client, db_session)
    tech_a = await user_crud.get_by_email(db_session, "tech-a@test.local")
    assert tech_a is not None
    tech_a_id = str(tech_a.id)
    await account(client, db_session, "ro@test.local", [BuiltinGroup.READONLY])
    readonly = await user_crud.get_by_email(db_session, "ro@test.local")
    assert readonly is not None
    readonly_id = str(readonly.id)

    refused = await client.patch(
        f"/api/v1/machines/{t.b.id}/maintenance",
        headers=t.admin,
        json={"maintenance_owner_id": tech_a_id},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "maintenance.owner.out_of_reach"
    # Sees everything, but cannot record a visit.
    refused = await client.patch(
        f"/api/v1/machines/{t.a.id}/maintenance",
        headers=t.admin,
        json={"maintenance_owner_id": readonly_id},
    )
    assert refused.status_code == 422, refused.text
    ok = await client.patch(
        f"/api/v1/machines/{t.a.id}/maintenance",
        headers=t.admin,
        json={"maintenance_owner_id": tech_a_id},
    )
    assert ok.status_code == 200, ok.text

    rooms = {}
    for name, site in (("Salle A", SITE_A), ("Salle B", SITE_B)):
        resp = await client.post(
            "/api/v1/rooms", headers=t.admin, json={"name": name, "location": site}
        )
        assert resp.status_code == 201, resp.text
        rooms[site] = resp.json()["id"]
    refused = await client.patch(
        f"/api/v1/rooms/{rooms[SITE_B]}/maintenance",
        headers=t.admin,
        json={"maintenance_owner_id": tech_a_id},
    )
    assert refused.status_code == 422, refused.text
    ok = await client.patch(
        f"/api/v1/rooms/{rooms[SITE_A]}/maintenance",
        headers=t.admin,
        json={"maintenance_owner_id": tech_a_id},
    )
    assert ok.status_code == 200, ok.text

    # The same owner sent again with another field is not re-checked: the
    # account confined since must not block the form (B08).
    from app.features.machine.models import Machine

    m = await db_session.get(Machine, t.b.id)
    m.maintenance_owner_id = uuid.UUID(tech_a_id)
    db_session.add(m)
    await db_session.commit()
    again = await client.patch(
        f"/api/v1/machines/{t.b.id}/maintenance",
        headers=t.admin,
        json={"maintenance_owner_id": tech_a_id, "maintenance_cycle_days": 30},
    )
    assert again.status_code == 200, again.text


async def test_assignable_users_for_a_poste_out_of_the_callers_reach(
    client, db_session
):
    """T32: ``machine_id`` is read within the caller's own scope."""
    t = await two_sites(client, db_session)
    hidden = await client.get(
        "/api/v1/checks/assignable-users",
        headers=t.scoped,
        params={"machine_id": str(t.b.id)},
    )
    assert hidden.status_code == 404, hidden.text
    seen = await client.get(
        "/api/v1/checks/assignable-users",
        headers=t.scoped,
        params={"machine_id": str(t.a.id)},
    )
    assert seen.status_code == 200, seen.text
