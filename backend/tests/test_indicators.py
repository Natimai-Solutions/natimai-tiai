"""``GET /stats/indicators`` (C9, plan-tendances-indicateurs §3): delays,
maintenance on time, command and deployment outcomes, month by month, under
the caller's scope and rights. Requires TIAI_TEST_DATABASE_URL."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.features.user.permissions import ALL_PERMISSIONS
from tests.scope_helpers import SITE_A, account, group, machine, two_sites


def _now() -> datetime:
    return datetime.now(UTC)


async def _zone(db_session, name: str) -> None:
    from app.features.setting import crud as setting_crud

    await setting_crud.set_value(db_session, "schedules.timezone", name, actor="t")
    await db_session.commit()


async def _get(client, headers, months: int = 12) -> dict:
    resp = await client.get(
        f"/api/v1/stats/indicators?months={months}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _total(rows: list[dict], field: str) -> int:
    return sum(r[field] for r in rows)


async def _retire(db_session, machine_id) -> None:
    from app.features.asset.models import Asset, AssetStatus

    db_session.add(Asset(machine_id=machine_id, status=AssetStatus.RETIRED))
    await db_session.commit()


# --- Verifications ---------------------------------------------------------------


async def _closed_check(db_session, machine_id, hours: float, **fields) -> None:
    from app.features.check.models import MachineCheck

    closed = _now() - timedelta(minutes=1)
    db_session.add(
        MachineCheck(
            machine_id=machine_id,
            requested_by="t@test.local",
            created_at=closed - timedelta(hours=hours),
            closed_at=closed,
            **fields,
        )
    )
    await db_session.commit()


async def test_closing_delays_median_and_ninth_decile(client, db_session):
    from app.features.check import crud as check_crud

    await _zone(db_session, "UTC")
    sites = await two_sites(client, db_session)
    gone = await machine(db_session, "GONE", location=SITE_A)
    await _retire(db_session, gone.id)
    # Antedated before its creation: counts as 0 h.
    for hours in (-5, 1, 2, 3, 10):
        await _closed_check(db_session, sites.a.id, hours)
    today = _now().date()
    await _closed_check(db_session, sites.a.id, 1, due_date=today)
    await _closed_check(db_session, sites.a.id, 1, due_date=today - timedelta(days=1))
    # Not closings anybody did, a poste out of the parc, out of scope.
    await _closed_check(
        db_session, sites.a.id, 50, closing_note_code=check_crud.CLOSED_BY_MERGE
    )
    await _closed_check(db_session, gone.id, 50)
    await _closed_check(db_session, sites.b.id, 50)

    scoped = (await _get(client, sites.scoped, months=1))["checks"]
    assert len(scoped) == 1
    month = scoped[0]
    assert month["closed"] == 7
    # [0, 1, 1, 1, 2, 3, 10]: the median is 1, the 9th decile 3 + 0.4 × 7.
    assert month["median_hours"] == 1.0
    assert month["p90_hours"] == pytest.approx(5.8)
    assert (month["with_due"], month["on_time_due"]) == (2, 1)

    admin = (await _get(client, sites.admin, months=1))["checks"][0]
    assert admin["closed"] == 8  # the other site's, never the retired one


async def test_a_section_is_null_without_the_right_to_its_source(client, db_session):
    g = await group(db_session, "Machines only", {"machine:read"}, None)
    headers = await account(client, db_session, "m@test.local", [g.id])
    body = await _get(client, headers)
    assert body["checks"] is None
    assert body["maintenance"] is None
    assert body["commands"] is None
    assert body["deployments"] is None
    assert len(body["months"]) == 12

    g2 = await group(db_session, "Commands", {"machine:read", "command:read"}, None)
    commands_only = await account(client, db_session, "c@test.local", [g2.id])
    body = await _get(client, commands_only)
    assert body["commands"] is not None
    # Deployments need the packages too.
    assert body["deployments"] is None


async def test_indicators_need_machine_read(client, db_session):
    g = await group(db_session, "Checks only", {"check:read"}, None)
    headers = await account(client, db_session, "k@test.local", [g.id])
    resp = await client.get("/api/v1/stats/indicators", headers=headers)
    assert resp.status_code == 403
    resp = await client.get(
        "/api/v1/stats/indicators?months=25",
        headers=await account(
            client,
            db_session,
            "adm@test.local",
            [(await group(db_session, "All", ALL_PERMISSIONS, None)).id],
        ),
    )
    assert resp.status_code == 422


# --- Maintenance --------------------------------------------------------------------


async def _maintenance(db_session, machine_id, days_ago: float, **fields) -> None:
    from app.features.intervention.models import Intervention

    db_session.add(
        Intervention(
            machine_id=machine_id,
            kind=fields.pop("kind", "maintenance"),
            performed_by="t@test.local",
            performed_at=_now() - timedelta(days=days_ago),
            **fields,
        )
    )
    await db_session.commit()


async def test_maintenance_on_time_against_the_previous_one_and_the_cycle(
    client, db_session
):
    from app.features.maintenance import crud as maintenance_crud
    from app.features.room.models import Room

    await _zone(db_session, "UTC")
    room = Room(name="Short cycle", location="S", maintenance_cycle_days=10)
    db_session.add(room)
    await db_session.flush()
    room_id = room.id
    await db_session.commit()

    def seen(days: float) -> datetime:
        return _now() - timedelta(days=days)

    # First one against first_seen (on time), second against the first (late).
    a = await machine(db_session, "A", first_seen=seen(200))
    await _maintenance(db_session, a.id, 150)
    await _maintenance(db_session, a.id, 10)
    # The previous one is before the period: still the reference (on time),
    # where first_seen would make it late.
    b = await machine(db_session, "B", first_seen=seen(1000))
    await _maintenance(db_session, b.id, 380)
    await _maintenance(db_session, b.id, 300)
    # The room's cycle (10 days): late, though on time on the parc's 90.
    c = await machine(db_session, "C", room_id=room_id, first_seen=seen(40))
    await _maintenance(db_session, c.id, 20)
    # The poste's own cycle (5 days) wins over its room's: late.
    d = await machine(
        db_session, "D", room_id=room_id, first_seen=seen(9), maintenance_cycle_days=5
    )
    await _maintenance(db_session, d.id, 1)
    # Excluded from maintenance: not counted.
    e = await machine(db_session, "E", first_seen=seen(9), maintenance_cycle_days=0)
    await _maintenance(db_session, e.id, 1)
    # « Maintenance non faite »: not a maintenance.
    await _maintenance(
        db_session,
        a.id,
        2,
        kind="other",
        title_code=maintenance_crud.SKIPPED_TITLE_CODE,
    )

    admin = await account(
        client,
        db_session,
        "adm@test.local",
        [(await group(db_session, "All", ALL_PERMISSIONS, None)).id],
    )
    rows = (await _get(client, admin))["maintenance"]
    assert _total(rows, "done") == 5
    assert _total(rows, "on_time") == 2


# --- Commands --------------------------------------------------------------------------


async def _command(db_session, machine_id, status: str, **fields) -> None:
    from app.features.command.models import Command

    now = _now() - timedelta(minutes=5)
    fields.setdefault("type", "quick_scan")
    fields.setdefault("expires_at", now + timedelta(hours=1))
    if status != "expired":
        fields.setdefault("finished_at", now)
    db_session.add(Command(machine_id=machine_id, status=status, **fields))
    await db_session.commit()


async def test_command_outcomes(client, db_session, monkeypatch):
    from app.core.config import settings
    from app.features.command import texts
    from app.features.trend.indicators import OPERATOR_CLOSURES

    await _zone(db_session, "UTC")
    sites = await two_sites(client, db_session)
    m = sites.a.id
    await _command(db_session, m, "succeeded")
    await _command(db_session, m, "succeeded")
    await _command(db_session, m, "failed")
    await _command(db_session, m, "failed", result_code=texts.unanswered(24).code)
    # Expired: finished_at stays NULL, the month is its expires_at's.
    await _command(db_session, m, "expired", expires_at=_now() - timedelta(hours=1))
    # Server commands, operator closures, still running, other site.
    await _command(db_session, m, "succeeded", type="wake_on_lan")
    for code in sorted(OPERATOR_CLOSURES):
        await _command(db_session, m, "failed", result_code=code)
    await _command(db_session, m, "running", finished_at=None)
    await _command(db_session, sites.b.id, "failed")

    body = await _get(client, sites.scoped, months=1)
    assert body["commands"] == [
        {
            "month": body["months"][0],
            "succeeded": 2,
            "failed": 1,
            "expired": 1,
            "unanswered": 1,
        }
    ]
    assert body["retention"] == {
        "commands_days": settings.COMMAND_RETENTION_DAYS,
        "schedule_runs_days": settings.SCHEDULE_RUN_RETENTION_DAYS,
    }
    monkeypatch.setattr(settings, "COMMAND_RETENTION_DAYS", 0)
    body = await _get(client, sites.scoped, months=1)
    assert body["retention"]["commands_days"] is None


def test_operator_closures_are_the_verdicts_codes():
    from app.features.trend.indicators import OPERATOR_CLOSURES

    assert OPERATOR_CLOSURES == {
        "command.merged",
        "package.deleted",
        "package.retired",
        "package.retired_after_queue",
        "package.changed_after_queue",
        "package.superseded",
        "directory.not_reader",
    }


async def test_the_month_is_the_consoles(client, db_session):
    from zoneinfo import ZoneInfo

    await _zone(db_session, "Pacific/Tahiti")
    sites = await two_sites(client, db_session)
    tahiti = ZoneInfo("Pacific/Tahiti")
    today = _now().astimezone(tahiti).date()
    first = today.replace(day=1)
    # 23:30 on the last day of last month in Tahiti: the 1st, 09:30 UTC.
    late = datetime.combine(
        first - timedelta(days=1), datetime.min.time(), tzinfo=tahiti
    ) + timedelta(hours=23, minutes=30)
    await _command(db_session, sites.a.id, "succeeded", finished_at=late)

    body = await _get(client, sites.admin, months=2)
    previous, current = body["commands"]
    assert previous["month"] == (first - timedelta(days=1)).strftime("%Y-%m")
    assert (previous["succeeded"], current["succeeded"]) == (1, 0)


# --- Deployments -------------------------------------------------------------------------


async def test_deployments_direct_and_scheduled(client, db_session):
    from app.features.schedule.models import RunStatus, Schedule, ScheduleRun

    await _zone(db_session, "UTC")
    sites = await two_sites(client, db_session)
    m = sites.a.id
    await _command(db_session, m, "succeeded", type="package_install")
    # A schedule without rings queues at stage 0: scheduled, never direct.
    await _command(db_session, m, "succeeded", type="package_install", schedule_stage=0)
    await _command(db_session, m, "failed", type="package_uninstall", schedule_stage=1)
    await _command(db_session, m, "succeeded", type="quick_scan", schedule_stage=0)

    schedule = Schedule(
        name="Déploiement",
        command_type="package_install",
        target={"kind": "all"},
        recurrence="once",
        created_by="t@test.local",
    )
    db_session.add(schedule)
    await db_session.flush()
    for finished in (_now() - timedelta(hours=1), _now() - timedelta(days=800)):
        db_session.add(
            ScheduleRun(
                schedule_id=schedule.id,
                status=RunStatus.HALTED,
                started_at=finished - timedelta(hours=2),
                finished_at=finished,
            )
        )
    await db_session.commit()

    admin = (await _get(client, sites.admin))["deployments"]
    assert _total(admin["direct"], "succeeded") == 1
    assert _total(admin["direct"], "failed") == 0
    assert _total(admin["scheduled"], "succeeded") == 1
    assert _total(admin["scheduled"], "failed") == 1
    assert sum(admin["halted_runs"]) == 1

    scoped = (await _get(client, sites.scoped))["deployments"]
    assert _total(scoped["scheduled"], "succeeded") == 1
    # A run spans several places: not for a confined account.
    assert scoped["halted_runs"] is None


async def test_halted_runs_need_the_schedules(client, db_session):
    perms = {"machine:read", "command:read", "package:read"}
    g = await group(db_session, "Deployments", perms, None)
    headers = await account(client, db_session, "d@test.local", [g.id])
    body = await _get(client, headers)
    assert body["deployments"]["halted_runs"] is None
    g2 = await group(db_session, "Deployments+", perms | {"schedule:read"}, None)
    headers2 = await account(client, db_session, "d2@test.local", [g2.id])
    assert (await _get(client, headers2))["deployments"]["halted_runs"] == [0] * 12


def test_months_back():
    from app.features.trend.crud import months_back

    assert months_back(date(2026, 11, 25), 1) == date(2026, 11, 1)
    assert months_back(date(2026, 11, 25), 12) == date(2025, 12, 1)
    assert months_back(date(2026, 1, 3), 2) == date(2025, 12, 1)


async def test_a_scoped_account_never_counts_another_sites_maintenance(
    client, db_session
):
    await _zone(db_session, "UTC")
    sites = await two_sites(client, db_session)
    await _maintenance(db_session, sites.b.id, 1)
    rows = (await _get(client, sites.scoped))["maintenance"]
    assert _total(rows, "done") == 0
    rows = (await _get(client, sites.admin))["maintenance"]
    assert _total(rows, "done") == 1
