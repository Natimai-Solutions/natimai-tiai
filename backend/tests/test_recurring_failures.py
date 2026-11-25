"""``GET /stats/recurring-failures`` (C9, plan-tendances-indicateurs §4).
Requires TIAI_TEST_DATABASE_URL."""

from datetime import UTC, datetime, timedelta

from app.features.user.permissions import ALL_PERMISSIONS
from app.features.user.scope import Scope
from tests.scope_helpers import SITE_A, SITE_B, account, group, machine


def _now() -> datetime:
    return datetime.now(UTC)


async def _incident(db_session, machine_id, *, days_ago: float = 1, kind="incident"):
    from app.features.intervention.models import Intervention

    db_session.add(
        Intervention(
            machine_id=machine_id,
            kind=kind,
            title="Panne",
            performed_by="t@test.local",
            performed_at=_now() - timedelta(days=days_ago),
        )
    )
    await db_session.commit()


async def _retire(db_session, machine_id) -> None:
    from app.features.asset.models import Asset, AssetStatus

    db_session.add(Asset(machine_id=machine_id, status=AssetStatus.RETIRED))
    await db_session.commit()


async def _admin(client, db_session):
    g = await group(db_session, "All", ALL_PERMISSIONS, None)
    return await account(client, db_session, "all@test.local", [g.id])


async def _get(client, headers, query: str = "") -> list[dict]:
    resp = await client.get(
        f"/api/v1/stats/recurring-failures?{query}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_by_model_against_the_parc_with_the_retired_apart(client, db_session):
    admin = await _admin(client, db_session)
    m1 = await machine(db_session, "M1", hw_model="OptiPlex 7010")
    m2 = await machine(db_session, "M2", hw_model="OptiPlex 7010")
    await machine(db_session, "M3", hw_model="OptiPlex 7010")
    m4 = await machine(db_session, "M4", hw_model="OptiPlex 7010")
    await _retire(db_session, m4.id)
    m5 = await machine(db_session, "M5")
    m6 = await machine(db_session, "M6", hw_model="Rare")
    m7 = await machine(db_session, "M7", hw_model="Dead")
    await _retire(db_session, m7.id)

    for m in (m1, m1, m2, m4, m5, m5, m6, m7, m7):
        await _incident(db_session, m.id)
    # Out of the period, or not an incident.
    await _incident(db_session, m6.id, days_ago=800)
    await _incident(db_session, m6.id, kind="maintenance")

    rows = await _get(client, admin)
    assert [r["hw_model"] for r in rows] == ["OptiPlex 7010", None, "Dead"]
    optiplex, unknown, dead = rows
    assert (
        optiplex["incidents"],
        optiplex["machines"],
        optiplex["parc"],
        optiplex["per_100"],
        optiplex["retired_incidents"],
        optiplex["retired_machines"],
    ) == (3, 2, 3, 100.0, 1, 1)
    assert (unknown["incidents"], unknown["parc"], unknown["per_100"]) == (2, 1, 200.0)
    # Every poste of the model retired: no parc, no rate, still shown.
    assert (dead["incidents"], dead["parc"], dead["per_100"]) == (0, 0, None)
    assert (dead["retired_incidents"], dead["retired_machines"]) == (2, 1)
    assert optiplex["last_at"] is not None

    # The threshold counts the retired ones too; « Rare » joins at 1.
    rows = await _get(client, admin, "min_incidents=1")
    assert "Rare" in [r["hw_model"] for r in rows]
    rows = await _get(client, admin, "min_incidents=3")
    assert [r["hw_model"] for r in rows] == ["OptiPlex 7010"]
    assert len(await _get(client, admin, "limit=1")) == 1


async def test_by_room_names_only_the_rooms_in_scope(client, db_session):
    from app.features.room.models import Building, Room

    building = Building(name="Bât. A", location=SITE_A)
    db_session.add(building)
    await db_session.flush()
    ra = Room(name="A1", building_id=building.id)
    rb = Room(name="B1", location=SITE_B)
    db_session.add_all([ra, rb])
    await db_session.flush()
    ra_id, rb_id = ra.id, rb.id
    await db_session.commit()

    g = await group(
        db_session, "Site A", ALL_PERMISSIONS, Scope(locations=frozenset({SITE_A}))
    )
    scoped = await account(client, db_session, "a@test.local", [g.id])
    admin = await _admin(client, db_session)

    # Visible by its agent's site, standing in a room of site B.
    x = await machine(db_session, "X", location=SITE_A, room_id=rb_id, hw_model="M")
    y = await machine(db_session, "Y", location=SITE_A, room_id=ra_id, hw_model="M")
    z = await machine(db_session, "Z", location=SITE_A, hw_model="M")
    other = await machine(db_session, "O", location=SITE_B, room_id=rb_id)
    for m in (x, x, y, y, z, z, other, other):
        await _incident(db_session, m.id)

    rows = await _get(client, scoped, "by=room")
    by_key = {(r["room_id"], r["out_of_scope"]): r for r in rows}
    assert set(by_key) == {(str(ra_id), False), (None, True), (None, False)}
    named = by_key[(str(ra_id), False)]
    assert (named["room_name"], named["building_name"], named["incidents"]) == (
        "A1",
        "Bât. A",
        2,
    )
    hidden = by_key[(None, True)]
    assert (hidden["room_name"], hidden["building_name"]) == (None, None)
    assert hidden["incidents"] == 2
    assert by_key[(None, False)]["incidents"] == 2
    assert str(rb_id) not in str(rows)
    # Total by room = total by model, the other site never counted.
    by_model = await _get(client, scoped, "by=hw_model")
    assert (
        sum(r["incidents"] for r in rows) == sum(r["incidents"] for r in by_model) == 6
    )

    rows = await _get(client, admin, "by=room")
    named = {r["room_name"]: r for r in rows if r["room_name"]}
    assert named["B1"]["incidents"] == 4
    assert named["B1"]["parc"] == 2
    assert not any(r["out_of_scope"] for r in rows)


async def test_recurring_failures_need_intervention_read(client, db_session):
    g = await group(db_session, "Machines", {"machine:read"}, None)
    headers = await account(client, db_session, "m@test.local", [g.id])
    resp = await client.get("/api/v1/stats/recurring-failures", headers=headers)
    assert resp.status_code == 403
    g2 = await group(db_session, "Interventions", {"intervention:read"}, None)
    headers2 = await account(client, db_session, "i@test.local", [g2.id])
    resp = await client.get("/api/v1/stats/recurring-failures", headers=headers2)
    assert resp.status_code == 403


async def test_parameters_are_bounded(client, db_session):
    admin = await _admin(client, db_session)
    for query in ("by=site", "min_incidents=0", "limit=0", "months=30"):
        resp = await client.get(
            f"/api/v1/stats/recurring-failures?{query}", headers=admin
        )
        assert resp.status_code == 422, query
