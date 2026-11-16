"""The fiche's previous/next: ``GET /machines/{id}/neighbours`` (audit T31).

The console used to work the neighbours out by reading the list in blocks of
50 and freezing them: a poste that moved into a block already read was never
seen again, and the search for the open poste gave up after 2,000 rows. The
server now answers from the list's own query and ORDER BY, so the contract
checked here is the strongest one available: for every poste of the list,
its neighbours and rank are exactly the list's, whatever the sort, the
direction, the ties, the NULLs, the filters and the caller's scope.
"""

import time
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import event, insert, update

from tests.scope_helpers import SITE_A, SITE_B, machine, two_sites

SORT_FIELDS = [
    "hostname",
    "domain",
    "location",
    "building",
    "room",
    "maintenance_due_at",
    "av_product_name",
    "wu_pending_count",
    "session_user_present",
    "last_seen",
    "hw_model",
    "ram_total_mb",
    "disk_free_percent",
    "agent_version",
    "usage_hours",
]


async def _admin(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session, email="admin@nav.local", password="pw", groups=[BuiltinGroup.ADMIN]
    )
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "admin@nav.local", "password": "pw"}
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _fleet(db_session) -> dict[str, object]:
    """Twelve postes built for ties and NULLs on every sortable column.

    Values are drawn from short cycles of different lengths, so that each
    column has ties (broken by the last contact, itself tied in threes, then
    the id) and absences, and no two columns line up.
    """
    from app.features.inventory.models import MachineSoftware, Software
    from app.features.machine.models import Machine
    from app.features.room.models import Building, Room
    from app.features.usage.accounting import hour_start
    from app.features.usage.models import MachineUptime

    now = datetime.now(UTC)
    building = Building(name="Bâtiment A", location="Lycée")
    db_session.add(building)
    await db_session.flush()
    rooms = [
        Room(name="Salle 1", building_id=building.id),
        Room(name="salle 1", building_id=building.id),
        Room(name="Atelier"),
    ]
    db_session.add_all(rooms)
    software = Software(name="Firefox")
    db_session.add(software)
    await db_session.flush()

    def cycle(values, i):
        return values[i % len(values)]

    stamps = [now - timedelta(minutes=k) for k in (1, 1, 1, 5, 5, 30)]
    machines = []
    for i in range(12):
        m = Machine(
            machine_uuid=f"nav-{i:02d}",
            hostname=cycle(["PC-B", "pc-a", None, "PC-A", "pc-c"], i),
            domain=cycle(["LYCEE", None, "lycee", "COLLEGE"], i),
            location=cycle(["Lycée", "Collège", None], i),
            room_id=cycle([rooms[0].id, rooms[1].id, None, rooms[2].id], i),
            av_product_name=cycle(["ESET", "Defender", None], i),
            wu_pending_count=cycle([0, 3, None, 3, 12], i),
            session_user_present=cycle([True, False, None], i),
            hw_model=cycle(["OptiPlex 7010", "OptiPlex 7010 AIO", None, "Latitude"], i),
            ram_total_mb=cycle([8192, 16384, None, 8192, 4096], i),
            system_volume_total_mb=cycle([100_000, 300_000, None, 0], i),
            system_volume_free_mb=cycle([33_333, 100_000, 50_000], i),
            agent_version=cycle(["0.9.0", "0.10.0", None, "0.9.0"], i),
            bios_date=cycle([date(2012, 1, 1), None, date(2024, 1, 1)], i),
            last_maintenance_at=cycle([None, now - timedelta(days=400), now], i),
            first_seen=now - timedelta(days=cycle([60, 60, 0], i)),
            last_seen=cycle(stamps, i),
        )
        db_session.add(m)
        machines.append(m)
    await db_session.flush()
    hour = hour_start(now)
    for i, m in enumerate(machines):
        for k in range(i % 4):
            db_session.add(
                MachineUptime(
                    machine_id=m.id,
                    hour=hour - timedelta(hours=k + 1),
                    seconds_on=cycle([3600, 1800], i),
                )
            )
        if i % 2:
            db_session.add(MachineSoftware(machine_id=m.id, software_id=software.id))
    ids = {"room": str(rooms[0].id), "software": software.id}
    await db_session.commit()
    return ids


async def _list_ids(client, headers, query: str) -> list[str]:
    ids: list[str] = []
    page = 1
    while True:
        resp = await client.get(
            f"/api/v1/machines?{query}&page={page}&page_size=200", headers=headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids += [m["id"] for m in body["items"]]
        if len(ids) >= body["total"]:
            return ids
        page += 1


async def _neighbours(client, headers, machine_id, query: str, cursor=None):
    suffix = f"&cursor={cursor}" if cursor else ""
    resp = await client.get(
        f"/api/v1/machines/{machine_id}/neighbours?{query}{suffix}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _id(neighbour) -> str | None:
    return neighbour["id"] if neighbour else None


async def _assert_matches_list(client, headers, query: str) -> list[str]:
    """Every poste's neighbours and rank are the list's, and walking the
    cursors from either end goes through the list in its order."""
    order = await _list_ids(client, headers, query)
    for rank, mid in enumerate(order):
        body = await _neighbours(client, headers, mid, query)
        assert body["rank"] == rank, (query, rank)
        assert body["total"] == len(order)
        assert _id(body["previous"]) == (order[rank - 1] if rank else None), query
        assert _id(body["next"]) == (
            order[rank + 1] if rank + 1 < len(order) else None
        ), query
    if order:
        # Forward with the cursors the answers hand out, then back.
        walked = [order[0]]
        body = await _neighbours(client, headers, order[0], query)
        while body["next"]:
            nxt = body["next"]
            walked.append(nxt["id"])
            body = await _neighbours(client, headers, nxt["id"], query, nxt["cursor"])
            assert body["rank"] == len(walked) - 1
        assert walked == order, query
        back = [walked[-1]]
        while body["previous"]:
            prev = body["previous"]
            back.append(prev["id"])
            body = await _neighbours(client, headers, prev["id"], query, prev["cursor"])
        assert back == order[::-1], query
    return order


async def test_neighbours_follow_the_list_on_every_sort(client, db_session):
    await _fleet(db_session)
    headers = await _admin(client, db_session)

    await _assert_matches_list(client, headers, "")
    for field in SORT_FIELDS:
        for desc in ("true", "false"):
            await _assert_matches_list(
                client, headers, f"sort_by={field}&sort_desc={desc}"
            )


async def test_neighbours_honour_every_filter(client, db_session):
    ids = await _fleet(db_session)
    headers = await _admin(client, db_session)

    for query in [
        "hw_model=OptiPlex 7010&exact=hw_model&sort_by=hostname&sort_desc=false",
        "hw_model=OptiPlex&sort_by=ram_total_mb",
        "hardware_aging=true",
        "hardware_aging=false&sort_by=disk_free_percent&sort_desc=false",
        "usage_hours_below=1.5&sort_by=usage_hours&sort_desc=false",
        "usage_hours_above=0.5&usage_days=3&sort_by=usage_hours",
        f"software_id={ids['software']}&sort_by=agent_version",
        f"room_id={ids['room']}&sort_by=session_user_present",
        "without_room=true&sort_by=maintenance_due_at&sort_desc=false",
        "search=pc-a&sort_by=domain",
        "ram_min_gb=8&sort_by=wu_pending_count&sort_desc=false",
        "maintenance_state=overdue",
    ]:
        order = await _assert_matches_list(client, headers, query)
        assert 0 < len(order) < 12, query


async def test_a_poste_out_of_the_list_has_no_place_in_it(client, db_session):
    from app.features.machine.models import Machine

    await _fleet(db_session)
    headers = await _admin(client, db_session)
    query = "hw_model=OptiPlex&sort_by=hostname"
    order = await _list_ids(client, headers, query)
    latitude = (
        await db_session.exec(
            Machine.__table__.select().where(Machine.hw_model == "Latitude")  # type: ignore[attr-defined]
        )
    ).first()

    body = await _neighbours(client, headers, latitude.id, query)

    assert body == {
        "previous": None,
        "next": None,
        "rank": None,
        "total": len(order),
        "cursor": None,
    }
    # Not a poste at all: the fiche's own 404.
    resp = await client.get(
        f"/api/v1/machines/{uuid.uuid4()}/neighbours?{query}", headers=headers
    )
    assert resp.status_code == 404


async def test_a_scoped_account_walks_its_own_postes_only(client, db_session):
    sites = await two_sites(client, db_session)
    for k in range(4):
        await machine(db_session, f"PC-A{k}", location=SITE_A)
        await machine(db_session, f"PC-B{k}", location=SITE_B)

    order = await _assert_matches_list(
        client, sites.scoped, "sort_by=hostname&sort_desc=false"
    )

    assert len(order) == 5
    assert str(sites.b.id) not in order
    # The other site's poste does not exist for this account, as on the fiche.
    resp = await client.get(
        f"/api/v1/machines/{sites.b.id}/neighbours", headers=sites.scoped
    )
    assert resp.status_code == 404
    # The administrator walks both sites.
    assert len(await _list_ids(client, sites.admin, "")) == 10


async def test_the_open_postes_heartbeat_does_not_move_its_neighbours(
    client, db_session
):
    """Audit B18: on the default sort, the last contact, the poste reached
    with ▶ heartbeats and goes to the top of the list. Its neighbours are
    those of the place it was reached at, not of the top of the list."""
    from app.features.machine.models import Machine

    now = datetime.now(UTC)
    ids = []
    for k in range(6):
        ids.append(
            (
                await machine(
                    db_session, f"HB-{k}", last_seen=now - timedelta(minutes=k + 1)
                )
            ).id
        )
    headers = await _admin(client, db_session)
    body = await _neighbours(client, headers, ids[2], "")
    reached = body["next"]
    assert reached["id"] == str(ids[3])

    await db_session.exec(
        update(Machine).where(Machine.id == ids[3]).values(last_seen=now)  # type: ignore[call-overload]
    )
    await db_session.commit()

    walked = await _neighbours(client, headers, ids[3], "", reached["cursor"])
    assert walked["rank"] == 3
    assert _id(walked["previous"]) == str(ids[2])
    assert _id(walked["next"]) == str(ids[4])
    # Without the cursor it would have been the top of the list.
    fresh = await _neighbours(client, headers, ids[3], "")
    assert fresh["rank"] == 0
    assert fresh["previous"] is None


async def test_a_poste_moving_ahead_of_the_reader_is_not_skipped(client, db_session):
    """The scenario the block reader lost (audit T31): the reader walks the
    list, and a poste further down moves to just ahead of them — inside the
    block the console had already read. It is the next poste shown."""
    from app.features.machine.models import Machine

    for k in range(120):
        await machine(db_session, f"PC-{k:03d}")
    headers = await _admin(client, db_session)
    query = "sort_by=hostname&sort_desc=false"
    order = await _list_ids(client, headers, query)

    body = await _neighbours(client, headers, order[30], query)
    seen = [order[30]]
    for _ in range(3):
        nxt = body["next"]
        seen.append(nxt["id"])
        body = await _neighbours(client, headers, nxt["id"], query, nxt["cursor"])
    # PC-090, two blocks down, is renamed to sort right after PC-035.
    await db_session.exec(
        update(Machine)  # type: ignore[call-overload]
        .where(Machine.id == uuid.UUID(order[90]))
        .values(hostname="PC-035b")
    )
    await db_session.commit()
    for _ in range(3):
        nxt = body["next"]
        seen.append(nxt["id"])
        body = await _neighbours(client, headers, nxt["id"], query, nxt["cursor"])

    assert seen == [*order[30:36], order[90]]
    assert body["rank"] == 36
    assert _id(body["next"]) == order[36]


async def test_a_cursor_is_checked(client, db_session):
    await _fleet(db_session)
    headers = await _admin(client, db_session)
    order = await _list_ids(client, headers, "sort_by=hostname")
    body = await _neighbours(client, headers, order[5], "sort_by=hostname")

    resp = await client.get(
        f"/api/v1/machines/{order[6]}/neighbours?sort_by=hostname&cursor=%%%",
        headers=headers,
    )
    assert resp.status_code == 422
    # Another sort's cursor is not this walk's: the poste's own place is used.
    other = await _neighbours(
        client, headers, order[6], "sort_by=ram_total_mb", body["next"]["cursor"]
    )
    plain = await _neighbours(client, headers, order[6], "sort_by=ram_total_mb")
    assert other == plain


async def test_one_statement_and_fast_on_three_thousand_postes(
    client, db_session, engine
):
    """O(1) queries whatever the list's size, and quick at the size of a
    large parc: the whole filtered list is one CTE, read once."""
    from app.features.machine.models import Machine

    now = datetime.now(UTC)
    await db_session.exec(
        insert(Machine),  # type: ignore[call-overload]
        params=[
            {
                "id": uuid.uuid4(),
                "machine_uuid": f"perf-{i:05d}",
                "hostname": f"PC-{i % 997:04d}",
                "hw_model": ["OptiPlex 7010", "Latitude", None][i % 3],
                "ram_total_mb": [8192, 16384, None, 4096][i % 4],
                "location": "Lycée",
                "first_seen": now - timedelta(days=60),
                "last_seen": now - timedelta(seconds=i % 600),
                "token_issued_at": now,
                "created_at": now,
                "updated_at": now,
            }
            for i in range(3000)
        ],
    )
    await db_session.commit()
    headers = await _admin(client, db_session)
    order = await _list_ids(client, headers, "sort_by=hostname")
    middle = order[1500]

    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    async def measured(url: str):
        statements.clear()
        event.listen(engine.sync_engine, "before_cursor_execute", record)
        try:
            started = time.perf_counter()
            resp = await client.get(url, headers=headers)
            elapsed = time.perf_counter() - started
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record)
        assert resp.status_code == 200, resp.text
        return resp.json(), elapsed, len(statements)

    # What one page of the list costs in statements around its own query
    # (session, settings, versions…): the neighbours pay the same, plus one.
    _, _, list_cost = await measured("/api/v1/machines?page_size=1")
    for query in ["", "sort_by=hostname", "hw_model=OptiPlex&sort_by=ram_total_mb"]:
        timings = []
        for _ in range(3):
            body, elapsed, count = await measured(
                f"/api/v1/machines/{middle}/neighbours?{query}"
            )
            timings.append(elapsed)
            assert sum("nav_rows" in s for s in statements) == 1, query
            assert count <= list_cost, statements
        # The whole request, authentication included.
        assert min(timings) < 0.2, (query, timings)
        if query == "sort_by=hostname":
            assert body["rank"] == 1500
            assert body["total"] == 3000
            assert _id(body["previous"]) == order[1499]
            assert _id(body["next"]) == order[1501]
