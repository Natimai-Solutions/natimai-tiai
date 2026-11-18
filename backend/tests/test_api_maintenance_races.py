"""Maintenance visits under concurrent requests: a part added while the visit
is being deleted, the same part retried several times at once, the creating
part sent twice.

Each test lets two or more requests of the same client interleave on the
event loop, each with its own database session — what two browser tabs, or a
retry racing its lost first attempt, do to the server.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import asyncio
import uuid

from sqlmodel import select

from tests.test_api_maintenance_sessions import (
    _admin,
    _journal,
    _machine,
    _room,
    _tech,
    _visit,
)


async def _lines(db_session):
    from app.features.intervention.models import Intervention

    db_session.expire_all()
    return list((await db_session.exec(select(Intervention))).all())


async def _visits(db_session):
    from app.features.maintenance.models import Maintenance

    db_session.expire_all()
    return list((await db_session.exec(select(Maintenance))).all())


async def _last_maintenances(db_session, machine_ids):
    from app.features.machine.models import Machine

    db_session.expire_all()
    rows = await db_session.exec(select(Machine))
    wanted = {uuid.UUID(m) for m in machine_ids}
    return {m.hostname: m.last_maintenance_at for m in rows.all() if m.id in wanted}


async def test_a_part_added_while_the_visit_is_deleted_leaves_no_orphan_line(
    client, db_session
):
    """The part and the deletion start together: whichever is served first,
    the visit is gone afterwards with every line it wrote — none survives
    detached from it (``maintenance_id`` NULL, still dating the postes'
    last maintenance, with no session left to delete)."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "Amphi")
    ms = [await _machine(db_session, f"M{i:03d}", room_id=room) for i in range(60)]
    for _attempt in range(6):
        visit = await _visit(client, admin, room, ms[:1])
        part = {"items": [{"machine_id": m} for m in ms[1:]]}
        added, deleted = await asyncio.gather(
            client.post(
                f"/api/v1/maintenance/{visit['id']}/lines", headers=admin, json=part
            ),
            client.delete(f"/api/v1/maintenance/{visit['id']}", headers=admin),
        )
        assert deleted.status_code == 204, deleted.text
        # Served before the deletion, or refused because the visit is gone.
        assert added.status_code in (200, 404), added.text
        if added.status_code == 404:
            assert added.json()["error"]["code"] == "maintenance.not_found"
        assert await _visits(db_session) == []
        assert await _lines(db_session) == []
        assert set((await _last_maintenances(db_session, ms)).values()) == {None}


async def test_a_part_arriving_after_the_deletion_started_is_refused_not_a_500(
    client, db_session
):
    """The deletion first, the part a few milliseconds behind it: the part
    waits on the visit, finds it gone and answers 404 — it used to insert
    lines against the deleted visit (a foreign-key failure, 500)."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "Amphi")
    ms = [await _machine(db_session, f"M{i:03d}", room_id=room) for i in range(120)]
    for delay in (0, 0.002, 0.005, 0.01, 0.02, 0.04, 0.08):
        visit = await _visit(client, admin, room, ms[:90])
        part = {"items": [{"machine_id": m} for m in ms[90:]]}

        async def late(delay=delay, visit=visit, part=part):
            await asyncio.sleep(delay)
            return await client.post(
                f"/api/v1/maintenance/{visit['id']}/lines", headers=admin, json=part
            )

        deleted, added = await asyncio.gather(
            client.delete(f"/api/v1/maintenance/{visit['id']}", headers=admin),
            late(),
        )
        assert deleted.status_code == 204, (delay, deleted.text)
        assert added.status_code in (200, 404), (delay, added.text)
        assert await _visits(db_session) == [], delay
        assert await _lines(db_session) == [], delay
        assert set((await _last_maintenances(db_session, ms)).values()) == {None}


async def test_a_part_retried_six_times_at_once_writes_one_line_per_poste(
    client, db_session
):
    """A retry racing its first attempt, six times over: the parts of one
    visit are served one after the other, and each finds what the previous
    one wrote (audit T30)."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "Amphi")
    ms = [await _machine(db_session, f"M{i:03d}", room_id=room) for i in range(40)]
    visit = await _visit(client, admin, room, ms[:1])
    part = {
        "items": [{"machine_id": m} for m in ms[1:30]],
        "skipped": [{"machine_id": m, "note": "Absent"} for m in ms[30:]],
    }
    answers = await asyncio.gather(
        *[
            client.post(
                f"/api/v1/maintenance/{visit['id']}/lines", headers=admin, json=part
            )
            for _ in range(6)
        ]
    )
    assert [r.status_code for r in answers] == [200] * 6
    got = (await client.get(f"/api/v1/maintenance/{visit['id']}", headers=admin)).json()
    assert got["machine_count"] == 30
    assert len(got["items"]) == 30
    assert len(got["skipped"]) == 10
    assert len(await _lines(db_session)) == 40
    for m in (ms[1], ms[29], ms[30], ms[39]):
        assert len(await _journal(client, admin, m)) == 1


async def test_the_creating_part_sent_four_times_at_once_is_one_visit(
    client, db_session
):
    """A retry racing its first attempt on the part that creates the visit:
    one creates it, the others wait for it and get it back — one visit, one
    line per poste, no error."""
    admin, _ = await _admin(client, db_session)
    tech, _ = await _tech(client, db_session)
    room = await _room(client, admin, "Amphi")
    ms = [await _machine(db_session, f"M{i:03d}", room_id=room) for i in range(40)]
    body = {
        "id": str(uuid.uuid4()),
        "room_id": room,
        "note": "Tout l'amphi",
        "items": [{"machine_id": m} for m in ms[:30]],
        "skipped": [{"machine_id": m, "note": "Absent"} for m in ms[30:]],
    }
    answers = await asyncio.gather(
        *[
            client.post("/api/v1/maintenance", headers=admin, json=body)
            for _ in range(4)
        ],
        # Another account sending the same id at the same instant.
        client.post("/api/v1/maintenance", headers=tech, json=body),
    )
    *own, foreign = answers
    statuses = sorted(r.status_code for r in answers)
    assert statuses in ([200, 200, 200, 201, 409], [201, 409, 409, 409, 409]), [
        r.text[:200] for r in answers
    ]
    (visit,) = await _visits(db_session)
    visit_id, author = str(visit.id), visit.performed_by
    assert visit_id == body["id"]
    assert len(await _lines(db_session)) == 40
    if foreign.status_code == 409:
        assert foreign.json()["error"]["code"] == "maintenance.session.id_taken"
        assert author == "admin@test.local"
        assert all(r.json()["machine_count"] == 30 for r in own)
    else:
        # Served first, the other account's request made the visit its own.
        assert author == "tech@test.local"
        assert all(r.status_code == 409 for r in own)
    for m in (ms[0], ms[29], ms[30], ms[39]):
        assert len(await _journal(client, admin, m)) == 1


async def _merge_waited_on(engine, keep, merged, request):
    """Run ``request`` while a merge of ``merged`` into ``keep`` holds its
    locks, uncommitted, until the request waits on them; then commit it."""
    from sqlalchemy import text
    from sqlmodel import col
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.machine import crud as machine_crud
    from app.features.machine.models import Machine

    async def lock_waiters() -> int:
        async with engine.connect() as conn:
            return await conn.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )

    async with AsyncSession(engine) as other:
        # What ``POST /machines/{keep}/merge`` does, held open.
        for locked in sorted((uuid.UUID(keep), uuid.UUID(merged))):
            await other.exec(
                select(Machine.id).where(col(Machine.id) == locked).with_for_update()
            )
        target = await other.get(Machine, uuid.UUID(keep))
        source = await other.get(Machine, uuid.UUID(merged))
        await machine_crud.merge_into(other, target=target, source=source)
        await other.flush()
        sent = asyncio.create_task(request())
        for _ in range(200):
            if await lock_waiters():
                break
            await asyncio.sleep(0.05)
        else:
            sent.cancel()
            raise AssertionError("the request never waited on the merge")
        await other.commit()
    return await sent


async def test_a_part_naming_a_poste_being_merged_is_refused_not_a_500(
    client, db_session, engine
):
    """A part of a visit names a poste merged at that moment (audit §6.4):
    it read the poste, then its lines waited on the merge's lock and met the
    deleted row — a foreign-key failure, 500. It now waits for the merge and
    answers the 404 that names the merged poste, writing nothing."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "Amphi")
    ms = [await _machine(db_session, f"M{i:03d}", room_id=room) for i in range(6)]
    visit = await _visit(client, admin, room, ms[:1])
    part = {"items": [{"machine_id": m} for m in ms[1:5]]}

    async def request():
        return await client.post(
            f"/api/v1/maintenance/{visit['id']}/lines", headers=admin, json=part
        )

    resp = await _merge_waited_on(engine, ms[5], ms[3], request)
    assert resp.status_code == 404, resp.text
    error = resp.json()["error"]
    assert error["code"] == "machine.not_found"
    assert error["details"]["machine_ids"] == [ms[3]]
    # Nothing of the part is written: the visit holds its first poste only.
    assert [str(line.machine_id) for line in await _lines(db_session)] == [ms[0]]
    # The part sent again without the merged poste is recorded.
    part = {"items": [{"machine_id": m} for m in ms[1:5] if m != ms[3]]}
    resp = await request()
    assert resp.status_code == 200, resp.text
    assert len(await _lines(db_session)) == 4


async def test_a_visit_naming_a_poste_being_merged_is_refused_not_a_500(
    client, db_session, engine
):
    """The creating part too: 404 naming the merged poste, no visit left."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "Amphi")
    ms = [await _machine(db_session, f"M{i:03d}", room_id=room) for i in range(4)]

    async def request():
        return await client.post(
            "/api/v1/maintenance",
            headers=admin,
            json={"room_id": room, "items": [{"machine_id": m} for m in ms[:3]]},
        )

    resp = await _merge_waited_on(engine, ms[3], ms[1], request)
    assert resp.status_code == 404, resp.text
    error = resp.json()["error"]
    assert error["code"] == "machine.not_found"
    assert error["details"]["machine_ids"] == [ms[1]]
    assert await _visits(db_session) == []
    assert await _lines(db_session) == []
