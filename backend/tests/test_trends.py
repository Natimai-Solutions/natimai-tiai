"""The daily photo of the dashboard (C9, plan-tendances-indicateurs §2):
parity with ``/stats/overview`` under every kind of scope, replacement,
frozen places, thresholds, the read API, the purge, the lock.

Requires TIAI_TEST_DATABASE_URL.
"""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlmodel import select

from app.features.user.permissions import ALL_PERMISSIONS
from app.features.user.scope import Scope
from tests.scope_helpers import account, group, machine

ADMIN_PERMS = ALL_PERMISSIONS


async def _record(engine, now: datetime | None = None) -> int:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.base import utcnow
    from app.features.trend import snapshot

    async with AsyncSession(engine) as session:
        cells = await snapshot.record(session, now or utcnow())
        await session.commit()
    return cells


async def _today(db_session) -> date:
    from app.features.base import utcnow
    from app.features.trend import crud

    return (await crud.period(db_session, 1, utcnow())).today


async def _sums(db_session, scope: Scope | None, day: date, keys) -> dict[str, int]:
    from app.features.trend import crud

    got = await crud.series(
        db_session, scope, start=day, end=day, step="day", keys=list(keys), today=day
    )
    return {k: v[0] for k, v in got.series.items()}


async def _snapshots(db_session):
    from app.features.trend.models import TrendSnapshot

    db_session.expire_all()
    return (await db_session.exec(select(TrendSnapshot))).all()


async def _parc(db_session):
    """Two sites, a building on site X, a room in it (R1) and one without
    building on site Y (R2), postes whose agent's site differs from their
    room's, one without any place, a retired one, threats, alerts, open
    verifications, a failed compliance check, a pending update."""
    from app.features.alert.models import MachineAlert
    from app.features.asset.models import Asset, AssetStatus
    from app.features.check.models import MachineCheck
    from app.features.room.models import Building, Room
    from app.features.threat.models import Threat

    b1 = Building(name="B1", location="Site X")
    db_session.add(b1)
    await db_session.flush()
    r1 = Room(name="R1", building_id=b1.id)
    r2 = Room(name="R2", location="Site Y")
    db_session.add_all([r1, r2])
    await db_session.flush()
    ids = {"b1": b1.id, "r1": r1.id, "r2": r2.id}
    await db_session.commit()

    m1 = await machine(db_session, "M1", location="Site A", room_id=ids["r1"])
    m2 = await machine(
        db_session,
        "M2",
        room_id=ids["r2"],
        wu_pending_count=3,
        compliance_total=5,
        compliance_passed=4,
        compliance_failed=["tpm"],
    )
    m3 = await machine(
        db_session,
        "M3",
        location="Site A",
        compliance_total=5,
        compliance_passed=5,
        compliance_failed=[],
        # Never maintained, seen 200 days ago: overdue on a 90-day cycle.
        first_seen=datetime.now(UTC) - timedelta(days=200),
    )
    await machine(db_session, "M4")
    m5 = await machine(db_session, "M5", location="Site A", room_id=ids["r1"])
    m6 = await machine(
        db_session, "M6", location="Site X", room_id=ids["r2"], wu_reboot_required=True
    )
    db_session.add_all(
        [
            Threat(machine_id=m1.id, status="active", detection_id="d1"),
            Threat(machine_id=m1.id, status="active", detection_id="d2"),
            Threat(machine_id=m5.id, status="active", detection_id="d3"),
            Threat(machine_id=m6.id, status="removed", detection_id="d4"),
            MachineAlert(machine_id=m1.id, rule="disk_low"),
            MachineAlert(machine_id=m1.id, rule="reboot_pending"),
            MachineAlert(machine_id=m6.id, rule="disk_low"),
            MachineAlert(
                machine_id=m3.id, rule="disk_low", resolved_at=datetime.now(UTC)
            ),
            MachineCheck(machine_id=m1.id, requested_by="t@test.local"),
            MachineCheck(machine_id=m2.id, requested_by="t@test.local"),
            MachineCheck(
                machine_id=m3.id,
                requested_by="t@test.local",
                closed_at=datetime.now(UTC),
            ),
            Asset(machine_id=m5.id, status=AssetStatus.RETIRED),
        ]
    )
    await db_session.commit()
    return ids


async def test_the_photo_summed_over_a_scope_is_the_dashboard(
    client, engine, db_session
):
    from app.features.alert.models import ALL_RULES
    from app.features.stats import counters

    ids = await _parc(db_session)
    scopes = {
        "parc": None,
        "site": Scope(locations=frozenset({"Site A"})),
        "building": Scope(buildings=frozenset({ids["b1"]})),
        "room": Scope(rooms=frozenset({ids["r2"]})),
        # Site X is R1's site through its building, and M6's agent site: M1
        # and M6 once each, never twice.
        "overlap": Scope(locations=frozenset({"Site X"}), rooms=frozenset({ids["r1"]})),
    }
    headers = {}
    for name, scope in scopes.items():
        g = await group(db_session, f"G-{name}", ADMIN_PERMS, scope)
        headers[name] = await account(client, db_session, f"{name}@test.local", [g.id])

    assert await _record(engine) > 0
    day = await _today(db_session)
    seen_totals = {}
    overdue = {}
    for name, scope in scopes.items():
        resp = await client.get("/api/v1/stats/overview", headers=headers[name])
        assert resp.status_code == 200, resp.text
        overview = resp.json()
        sums = await _sums(db_session, scope, day, counters.ALL_KEYS)
        for key in counters.BASE_KEYS:
            assert sums[key] == overview[key], (name, key)
        assert sums["outdated"] == overview["outdated"], name
        for rule in ALL_RULES:
            assert sums[f"alerts.{rule.value}"] == overview["alerts_by_rule"].get(
                rule.value, 0
            ), (name, rule)
        for key in counters.COMPLIANCE_KEYS:
            check = key.removeprefix("compliance.")
            assert sums[key] == overview["compliance_by_check"].get(check, 0), (
                name,
                key,
            )
        seen_totals[name] = overview["total"]
        overdue[name] = overview["machines_maintenance_overdue"]
    # The fixture does exercise what the parity is about.
    assert seen_totals == {"parc": 5, "site": 2, "building": 1, "room": 2, "overlap": 2}
    assert overdue["parc"] == overdue["site"] == 1


async def test_zeros_are_not_stored_and_a_second_photo_replaces_the_first(
    engine, db_session
):
    await machine(db_session, "PC-1", location="Site A")
    await machine(db_session, "PC-2", location="Site B")

    assert await _record(engine) == 2
    first = {s.id for s in await _snapshots(db_session)}
    assert await _record(engine) == 2
    second = await _snapshots(db_session)

    assert len(second) == 2
    assert first.isdisjoint({s.id for s in second})
    for snap in second:
        assert snap.counters["total"] == 1
        assert all(value != 0 for value in snap.counters.values())


async def test_a_poste_moved_during_the_day_is_in_its_new_cell_only(engine, db_session):
    from app.features.machine.models import Machine
    from app.features.room.models import Room

    r1, r2 = Room(name="R1", location="S"), Room(name="R2", location="S")
    db_session.add_all([r1, r2])
    await db_session.flush()
    r1_id, r2_id = r1.id, r2.id
    await db_session.commit()
    pc = await machine(db_session, "PC", room_id=r1_id)
    await _record(engine)

    row = await db_session.get(Machine, pc.id)
    assert row is not None
    row.room_id = r2_id
    await db_session.commit()
    await _record(engine)

    snaps = await _snapshots(db_session)
    assert [(s.room_id, s.counters.get("total")) for s in snaps] == [(r2_id, 1)]


async def test_the_day_is_the_consoles(engine, db_session):
    from app.features.setting import crud as setting_crud
    from app.features.trend.models import TrendDay

    await setting_crud.set_value(
        db_session, "schedules.timezone", "Pacific/Tahiti", actor="t"
    )
    await db_session.commit()
    await machine(db_session, "PC")

    # 05:00 UTC on the 26th is 19:00 on the 25th in Tahiti (UTC−10).
    await _record(engine, datetime(2026, 11, 26, 5, 0, tzinfo=UTC))
    days = (await db_session.exec(select(TrendDay))).all()
    assert [(d.day, d.zone) for d in days] == [(date(2026, 11, 25), "Pacific/Tahiti")]

    await setting_crud.set_value(db_session, "schedules.timezone", "UTC", actor="t")
    await db_session.commit()
    await _record(engine, datetime(2026, 11, 26, 5, 0, tzinfo=UTC))
    db_session.expire_all()
    got = sorted(d.day for d in (await db_session.exec(select(TrendDay))).all())
    assert got == [date(2026, 11, 25), date(2026, 11, 26)]


async def test_a_room_moved_then_deleted_keeps_its_history_with_its_old_building(
    engine, db_session
):
    from app.features.room.models import Building, Room

    old, new = Building(name="Old", location="S1"), Building(name="New", location="S2")
    db_session.add_all([old, new])
    await db_session.flush()
    room = Room(name="R", building_id=old.id)
    db_session.add(room)
    await db_session.flush()
    old_id, new_id, room_id = old.id, new.id, room.id
    await db_session.commit()
    await machine(db_session, "PC", room_id=room_id)
    await _record(engine)
    day = await _today(db_session)

    row = await db_session.get(Room, room_id)
    assert row is not None
    row.building_id = new_id
    await db_session.commit()
    await db_session.delete(row)
    await db_session.commit()

    def total(scope):
        return _sums(db_session, scope, day, ["total"])

    assert (await total(Scope(buildings=frozenset({old_id}))))["total"] == 1
    assert (await total(Scope(locations=frozenset({"S1"}))))["total"] == 1
    assert (await total(Scope(buildings=frozenset({new_id}))))["total"] == 0
    assert (await total(Scope(locations=frozenset({"S2"}))))["total"] == 0
    # A scope that names the deleted room keeps its frozen history (§1).
    assert (await total(Scope(rooms=frozenset({room_id}))))["total"] == 1


async def test_an_empty_scope_reads_zeros_on_photographed_days_only(engine, db_session):
    await machine(db_session, "PC", location="S")
    await _record(engine)
    day = await _today(db_session)
    from app.features.trend import crud

    got = await crud.series(
        db_session,
        Scope(),
        start=day - timedelta(days=1),
        end=day,
        step="day",
        keys=["total"],
        today=day,
    )
    assert got.series == {"total": [None, 0]}


# --- Thresholds ---------------------------------------------------------------


async def test_the_thresholds_are_kept_and_their_changes_reported(
    client, engine, db_session
):
    from app.features.setting import crud as setting_crud
    from app.features.trend.models import TrendDay

    admin = await _admin(client, db_session)
    await machine(db_session, "PC")
    yesterday = datetime.now(UTC) - timedelta(days=1)
    await _record(engine, yesterday)
    await setting_crud.set_value(
        db_session, setting_crud.KEY_LOW_DISK, 15, actor="admin"
    )
    await setting_crud.set_value(db_session, setting_crud.KEY_CYCLE, 30, actor="admin")
    await db_session.commit()
    await _record(engine)

    days = (await db_session.exec(select(TrendDay).order_by(TrendDay.day))).all()
    assert days[0].policies["fleet.low_disk_free_percent"] == 10
    assert days[1].policies["fleet.low_disk_free_percent"] == 15
    assert set(days[1].policies) >= {
        "fleet.hardware_aging_years",
        "fleet.inactive_after_days",
        "fleet.signature_max_age_days",
        "fleet.agent_expected_version",
        "usage.window_days",
        "usage.low_hours",
        "usage.high_hours",
        "maintenance.cycle_days",
        "maintenance.due_soon_days",
        "compliance.patch_grace_days",
        "compliance.unencrypted_scope",
    }

    resp = await client.get("/api/v1/stats/trends?months=1", headers=admin)
    assert resp.status_code == 200, resp.text
    changes = {
        (c["key"], c["before"], c["after"]) for c in resp.json()["policy_changes"]
    }
    assert ("fleet.low_disk_free_percent", 10, 15) in changes
    assert ("maintenance.cycle_days", 90, 30) in changes
    assert len(changes) == 2


# --- The read API -----------------------------------------------------------------


async def _admin(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    return await account(
        client,
        db_session,
        f"admin-{uuid.uuid4().hex[:6]}@test.local",
        [BuiltinGroup.ADMIN],
    )


async def _photo(db_session, day: date, cells: list[tuple[str | None, dict]]) -> None:
    """A photographed day written by hand: ``(location, counters)`` cells."""
    from app.features.trend.models import TrendDay, TrendSnapshot

    db_session.add(
        TrendDay(day=day, taken_at=datetime.now(UTC), zone="UTC", policies={})
    )
    await db_session.flush()
    for location, values in cells:
        db_session.add(TrendSnapshot(day=day, location=location, counters=values))
    await db_session.commit()


async def _utc(db_session):
    from app.features.setting import crud as setting_crud

    await setting_crud.set_value(db_session, "schedules.timezone", "UTC", actor="t")
    await db_session.commit()
    return datetime.now(UTC).date()


async def test_trends_need_machine_read(client, db_session):
    g = await group(db_session, "Checks only", {"check:read"}, None)
    headers = await account(client, db_session, "c@test.local", [g.id])
    assert (
        await client.get("/api/v1/stats/trends", headers=headers)
    ).status_code == 403


async def test_trends_gaps_zeros_and_keys(client, db_session):
    today = await _utc(db_session)
    admin = await _admin(client, db_session)
    g = await group(
        db_session, "Site A", ADMIN_PERMS, Scope(locations=frozenset({"A"}))
    )
    scoped = await account(client, db_session, "a@test.local", [g.id])
    two_ago = today - timedelta(days=2)
    await _photo(db_session, two_ago, [("A", {"total": 3, "open_checks": 1})])
    await _photo(db_session, today, [("B", {"total": 4})])

    resp = await client.get(
        "/api/v1/stats/trends?months=1&step=day&keys=total,open_checks,outdated",
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["series"]) == {"total", "open_checks", "outdated"}
    by_day = dict(zip(body["days"], body["series"]["total"], strict=True))
    assert by_day[two_ago.isoformat()] == 3
    assert by_day[today.isoformat()] == 4
    # A day never photographed is a gap.
    assert by_day[(today - timedelta(days=1)).isoformat()] is None
    checks = dict(zip(body["days"], body["series"]["open_checks"], strict=True))
    # Photographed, no cell carries the key: 0.
    assert checks[today.isoformat()] == 0
    outdated = dict(zip(body["days"], body["series"]["outdated"], strict=True))
    assert outdated[today.isoformat()] == 4
    assert body["provisional_day"] == today.isoformat()
    assert body["since"] == two_ago.isoformat()

    # Confined to A: today is photographed, but no cell of A — zeros.
    mine = (
        await client.get(
            "/api/v1/stats/trends?months=1&step=day&keys=total", headers=scoped
        )
    ).json()
    mine_by_day = dict(zip(mine["days"], mine["series"]["total"], strict=True))
    assert mine_by_day[today.isoformat()] == 0
    assert mine_by_day[two_ago.isoformat()] == 3

    # No keys: the console's default series.
    from app.features.trend.crud import DEFAULT_KEYS

    default = (await client.get("/api/v1/stats/trends", headers=admin)).json()
    assert list(default["series"]) == list(DEFAULT_KEYS)


async def test_trends_by_week_take_the_last_day_photographed(client, db_session):
    today = await _utc(db_session)
    admin = await _admin(client, db_session)
    this_monday = today - timedelta(days=today.weekday())
    week_a = this_monday - timedelta(days=21)
    await _photo(db_session, week_a, [("A", {"total": 1})])
    await _photo(db_session, week_a + timedelta(days=2), [("A", {"total": 2})])

    body = (
        await client.get("/api/v1/stats/trends?months=6&keys=total", headers=admin)
    ).json()
    assert body["step"] == "week"
    points = dict(zip(body["days"], body["series"]["total"], strict=True))
    assert points[(week_a + timedelta(days=2)).isoformat()] == 2
    assert week_a.isoformat() not in points
    # The week after, never photographed: a gap.
    gaps = [
        v
        for d, v in points.items()
        if week_a + timedelta(days=7)
        <= date.fromisoformat(d)
        < week_a + timedelta(days=14)
    ]
    assert gaps == [None]


async def test_trends_validate_their_parameters(client, db_session):
    admin = await _admin(client, db_session)
    for query in ("months=0", "months=25", "keys=total,nope", "step=month"):
        resp = await client.get(f"/api/v1/stats/trends?{query}", headers=admin)
        assert resp.status_code == 422, query
    empty = (await client.get("/api/v1/stats/trends", headers=admin)).json()
    assert empty["since"] is None
    assert all(v is None for series in empty["series"].values() for v in series)


# --- Worker: purge, lock, failure ---------------------------------------------------


@pytest.fixture
def worker(engine, monkeypatch):
    from app.core import worker as module

    monkeypatch.setattr(module, "engine", engine)
    return module


async def test_the_purge_drops_old_days_with_their_cells(
    worker, db_session, monkeypatch
):
    from app.features.trend.models import TrendDay

    monkeypatch.setattr(worker.settings, "TREND_RETENTION_DAYS", 400)
    today = datetime.now(UTC).date()
    await _photo(db_session, today - timedelta(days=401), [("A", {"total": 1})])
    await _photo(db_session, today - timedelta(days=399), [("A", {"total": 2})])

    assert await worker.purge_trends() == 1
    db_session.expire_all()
    days = (await db_session.exec(select(TrendDay.day))).all()
    assert days == [today - timedelta(days=399)]
    assert [s.counters for s in await _snapshots(db_session)] == [{"total": 2}]


async def test_the_worker_job_takes_the_photo(worker, db_session):
    await machine(db_session, "PC", location="A")
    assert await worker.snapshot_trends() == 1
    assert len(await _snapshots(db_session)) == 1


async def test_two_photos_at_once_are_serialised(engine, db_session):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.base import utcnow
    from app.features.trend import snapshot

    await machine(db_session, "PC", location="A")
    first = AsyncSession(engine)
    await snapshot.record(first, utcnow())  # holds the lock, uncommitted

    second = asyncio.create_task(_record(engine))
    await asyncio.sleep(0.5)
    assert not second.done()

    await first.commit()
    await first.close()
    assert await asyncio.wait_for(second, timeout=10) == 1
    assert len(await _snapshots(db_session)) == 1


async def test_a_failed_photo_leaves_the_previous_one(engine, db_session, monkeypatch):
    from app.features.setting import crud as setting_crud
    from app.features.trend import snapshot
    from app.features.trend.models import TrendDay

    await machine(db_session, "PC", location="A")
    await _record(engine)
    before = [(s.id, s.counters) for s in await _snapshots(db_session)]

    await setting_crud.set_value(
        db_session, setting_crud.KEY_LOW_DISK, 25, actor="admin"
    )
    await db_session.commit()

    async def boom(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(snapshot, "take", boom)
    with pytest.raises(RuntimeError):
        await _record(engine)

    assert [(s.id, s.counters) for s in await _snapshots(db_session)] == before
    days = (await db_session.exec(select(TrendDay))).all()
    assert days[0].policies["fleet.low_disk_free_percent"] == 10


async def test_a_merge_leaves_the_photos_alone(engine, db_session):
    from app.features.machine import crud as machine_crud
    from app.features.machine.models import Machine

    a = await machine(db_session, "A", location="A")
    b = await machine(db_session, "B", location="B")
    await _record(engine)
    before = sorted(
        (s.location, s.counters["total"]) for s in await _snapshots(db_session)
    )

    target = await db_session.get(Machine, a.id)
    source = await db_session.get(Machine, b.id)
    assert target is not None and source is not None
    await machine_crud.merge_into(db_session, target=target, source=source)
    await db_session.commit()

    after = sorted(
        (s.location, s.counters["total"]) for s in await _snapshots(db_session)
    )
    assert after == before == [("A", 1), ("B", 1)]
