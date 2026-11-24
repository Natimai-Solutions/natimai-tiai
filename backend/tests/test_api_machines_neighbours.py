"""The fiche's previous/next: ``GET /machines/{id}/neighbours`` (audit T31).

The console used to work the neighbours out by reading the list in blocks of
50 and freezing them: a poste that moved into a block already read was never
seen again, and the search for the open poste gave up after 2,000 rows. The
server now answers from the list's own query and ORDER BY, so the contract
checked here is the strongest one available: for every poste of the list,
its neighbours and rank are exactly the list's, whatever the sort, the
direction, the ties, the NULLs, the filters and the caller's scope.
"""

import base64
import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, insert, update

from tests.scope_helpers import SITE_A, SITE_B, machine, two_sites


def _sort_fields() -> list[str]:
    """Every sort the API offers, read off its own type: a field added to
    the list and forgotten here would never be walked."""
    from typing import get_args

    from app.api.routes.machines import MachineSortField

    return list(get_args(MachineSortField))


SORT_FIELDS = _sort_fields()


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
    # Case twins, on two sites: a name is unique in its building — and a
    # building's on its site — whatever its case, and the sorts fold it.
    building = Building(name="Bâtiment A", location="Lycée")
    twin = Building(name="bâtiment a", location="Collège")
    db_session.add_all([building, twin])
    await db_session.flush()
    rooms = [
        Room(name="Salle 1", building_id=building.id),
        Room(name="salle 1", building_id=twin.id),
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
            compliance_total=cycle([9, 9, None, 8, 9], i),
            compliance_passed=cycle([9, 7, None, 8, 7], i),
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


def _forged(sort_by: str, *values) -> str:
    """A cursor as the server writes them, around values it never wrote."""
    payload = {"s": sort_by, "d": True, "v": list(values)}
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


_STAMP = {"t": "2026-11-17T00:00:00+00:00"}
# Well-formed cursors of the right sort and the right kinds, whose values no
# column holds: each used to reach PostgreSQL as a parameter it refuses.
_UNUSABLE_CURSORS = {
    "nul in a string": ("hostname", "a\u0000b", _STAMP),
    "lone surrogate": ("hostname", "\ud800", _STAMP),
    "nul in a room": ("room", "salle\u0000", _STAMP),
    "nul in a raw version": ("agent_version", "0.9\u0000", _STAMP),
    "integer past int4": ("wu_pending_count", 2**31, _STAMP),
    "integer below int4": ("wu_pending_count", -(2**31) - 1, _STAMP),
    "integer past any column": ("wu_pending_count", 10**30, _STAMP),
    "memory past int4": ("ram_total_mb", 2**40, _STAMP),
    "naive date": ("", {"t": "2026-11-17T00:00:00"}),
    "naive tie-breaker": ("hostname", "pc-a", {"t": "2026-11-17T00:00:00"}),
    "naive due date": ("maintenance_due_at", {"t": "2026-11-17T00:00:00"}, _STAMP),
    "float nan": ("disk_free_percent", {"f": "nan"}, _STAMP),
    "float infinity": ("disk_free_percent", {"f": "inf"}, _STAMP),
    "decimal nan": ("disk_free_percent", {"n": "NaN"}, _STAMP),
    "decimal signalling nan": ("disk_free_percent", {"n": "sNaN"}, _STAMP),
    "decimal infinity": ("disk_free_percent", {"n": "-Infinity"}, _STAMP),
    "decimal past numeric": ("disk_free_percent", {"n": "1e999999"}, _STAMP),
    "integer past numeric": ("disk_free_percent", 10**400, _STAMP),
    "zero finer than numeric": ("disk_free_percent", {"n": "0E-20000"}, _STAMP),
    "decimal finer than numeric": ("disk_free_percent", {"n": "1E-16384"}, _STAMP),
    "decimal at numeric's edge": ("disk_free_percent", {"n": "1E-16383"}, _STAMP),
    "hours finer than numeric": ("usage_hours", {"n": "-1E-20000"}, _STAMP),
    "hours finer than float": ("usage_hours", {"n": "1E-400"}, _STAMP),
    "hours infinite": ("usage_hours", {"f": "-inf"}, _STAMP),
    "hours past float": ("usage_hours", {"n": "1e400"}, _STAMP),
    "integer for a flag": ("session_user_present", 1, _STAMP),
    "flag for a count": ("wu_pending_count", True, _STAMP),
    "flag for a percentage": ("disk_free_percent", True, _STAMP),
    "text for a count": ("wu_pending_count", "3", _STAMP),
}


@pytest.mark.parametrize("name", list(_UNUSABLE_CURSORS))
async def test_a_tampered_cursor_is_ignored_never_a_500(client, db_session, name):
    """Only the caller's own request was at stake, and it still must answer:
    the poste's current place, as for another sort's cursor."""
    sort_by, *values = _UNUSABLE_CURSORS[name]
    await _fleet(db_session)
    headers = await _admin(client, db_session)
    query = f"sort_by={sort_by}" if sort_by else ""
    order = await _list_ids(client, headers, query)
    plain = await _neighbours(client, headers, order[6], query)
    forged = await _neighbours(
        client, headers, order[6], query, _forged(sort_by, *values)
    )
    assert forged == plain


async def test_a_usable_cursor_of_every_kind_is_still_used(client, db_session):
    """The bounds must not turn away what the server itself hands out, nor a
    place no poste holds any more: the walk goes on from there."""
    await _fleet(db_session)
    headers = await _admin(client, db_session)
    for sort_by, value in (
        ("hostname", "pc-b"),
        ("wu_pending_count", 2**31 - 1),
        ("wu_pending_count", -(2**31)),
        ("ram_total_mb", 9000),
        ("disk_free_percent", {"n": "33.5"}),
        ("disk_free_percent", {"n": "0E-30"}),
        ("disk_free_percent", {"n": "33.333333333333333333333333333333"}),
        ("usage_hours", {"n": "1E-20"}),
        ("disk_free_percent", {"f": "33.5"}),
        ("disk_free_percent", 34),
        ("usage_hours", {"f": "0.75"}),
        ("session_user_present", True),
        ("maintenance_due_at", _STAMP),
    ):
        query = f"sort_by={sort_by}"
        cursor = _forged(sort_by, value, _STAMP)
        for mid in (await _list_ids(client, headers, query))[:3]:
            body = await _neighbours(client, headers, mid, query, cursor)
            # Used, not replaced by the poste's own place: it comes back as is.
            assert body["cursor"] == _encode(sort_by, value)
    # Dates at either end of the calendar are dates still.
    mid = (await _list_ids(client, headers, ""))[0]
    for edge in ("0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"):
        await _neighbours(client, headers, mid, "", _forged("", {"t": edge}))


def _encode(sort_by: str, value) -> str:
    raw = json.dumps(
        {"s": sort_by, "d": True, "v": [value, _STAMP]}, separators=(",", ":")
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "value", [{"n": "abc"}, {"f": "abc"}, {"t": "yesterday"}, {"u": "x"}, [1], 1.5]
)
async def test_a_cursor_that_cannot_be_read_is_a_422(client, db_session, value):
    await _fleet(db_session)
    headers = await _admin(client, db_session)
    order = await _list_ids(client, headers, "sort_by=disk_free_percent")
    resp = await client.get(
        f"/api/v1/machines/{order[0]}/neighbours?sort_by=disk_free_percent"
        f"&cursor={_forged('disk_free_percent', value, _STAMP)}",
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["message"] == "Malformed cursor"


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
