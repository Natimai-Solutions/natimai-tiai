"""Schedules (C3): the clock (pure), then through the API and the worker's
runner (require TIAI_TEST_DATABASE_URL) — written in the console's zone,
run on behalf of their author checked again, suspended when a right is
lost, « réveiller d'abord » / « éteindre ensuite », forbidden windows,
rings, scope and merge."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import col, select

from app.features.schedule import windows
from tests.scope_helpers import SITE_A, account, group, machine, two_sites
from tests.test_api_maintenance import _admin, _tech

TAHITI = ZoneInfo("Pacific/Tahiti")


# --- The clock ----------------------------------------------------------------


def test_next_weekly_is_local_and_strictly_after():
    # Wednesday 2026-11-25 07:00 in Tahiti is 17:00 UTC.
    after = datetime(2026, 11, 25, 16, 0, tzinfo=UTC)
    nxt = windows.next_weekly([2], "07:00", TAHITI, after)
    assert nxt == datetime(2026, 11, 25, 17, 0, tzinfo=UTC)
    # At that very instant: next week.
    assert windows.next_weekly([2], "07:00", TAHITI, nxt) == nxt + timedelta(days=7)
    # Two days a week: the nearer.
    assert windows.next_weekly([4, 0], "18:30", TAHITI, after) == datetime(
        2026, 11, 28, 4, 30, tzinfo=UTC
    )
    assert windows.next_weekly([], "07:00", TAHITI, after) is None


def test_next_weekly_across_a_clock_change():
    paris = ZoneInfo("Europe/Paris")
    # Sunday 2026-03-29, summer time from 02:00: 08:00 is 06:00 UTC.
    after = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)
    assert windows.next_weekly([6], "08:00", paris, after) == datetime(
        2026, 3, 29, 6, 0, tzinfo=UTC
    )


def test_windows_read_and_contain():
    parsed = windows.parse_windows(
        [
            {"days": [0, 1, 2, 3, 4], "start": "07:30", "end": "12:00"},
            {"days": [7], "start": "07:30", "end": "12:00"},  # no such day
            {"days": [0], "start": "12:00", "end": "08:00"},  # backwards
            "nonsense",
        ]
    )
    assert len(parsed) == 1
    window = parsed[0]
    monday = datetime(2026, 11, 23, 9, 0, tzinfo=TAHITI)
    assert window.contains(monday)
    assert not window.contains(monday.replace(hour=12))  # end excluded
    assert not window.contains(monday + timedelta(days=5))  # Saturday
    policy = windows.SchedulePolicy("Pacific/Tahiti", TAHITI, (window,))
    assert windows.weekly_in_forbidden([0, 5], "08:00", policy) == window
    assert windows.weekly_in_forbidden([5, 6], "08:00", policy) is None
    assert windows.weekly_in_forbidden([0], "18:00", policy) is None


# --- Helpers ------------------------------------------------------------------


def _local(instant: datetime) -> str:
    return instant.astimezone(TAHITI).strftime("%Y-%m-%dT%H:%M")


def _once(at: datetime, **fields):
    return {
        "name": "Analyse rapide",
        "command_type": "quick_scan",
        "target": {"kind": "all"},
        "recurrence": "once",
        "run_at_local": _local(at),
        **fields,
    }


async def _create(client, headers, payload, status=201):
    resp = await client.post("/api/v1/schedules", headers=headers, json=payload)
    assert resp.status_code == status, resp.text
    return resp.json()


async def _run(db_session, now):
    from app.features.schedule import runner

    ran = await runner.run_due(db_session, now)
    await runner.follow_runs(db_session, now)
    db_session.expire_all()
    return ran


async def _runs(db_session, schedule_id):
    from app.features.schedule.models import ScheduleRun

    db_session.expire_all()
    return list(
        (
            await db_session.exec(
                select(ScheduleRun)
                .where(col(ScheduleRun.schedule_id) == uuid.UUID(schedule_id))
                .order_by(col(ScheduleRun.started_at))
            )
        ).all()
    )


async def _commands(db_session, **where):
    from app.features.command.models import Command

    db_session.expire_all()
    stmt = select(Command)
    for name, value in where.items():
        stmt = stmt.where(getattr(Command, name) == value)
    return list((await db_session.exec(stmt)).all())


async def _schedule(db_session, schedule_id):
    from app.features.schedule.models import Schedule

    db_session.expire_all()
    return await db_session.get(Schedule, uuid.UUID(schedule_id))


# --- Writing ------------------------------------------------------------------


async def test_a_one_off_runs_once_on_behalf_of_its_author(client, db_session):
    headers, _ = await _admin(client, db_session)
    a = await machine(db_session, "PC-A")
    b = await machine(db_session, "PC-B")
    at = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=2)
    created = await _create(client, headers, _once(at))
    assert created["state"] == "active"
    assert created["next_run_local"] == _local(at)
    assert created["created_by"] == "admin@test.local"

    listed = (await client.get("/api/v1/schedules", headers=headers)).json()
    assert listed["timezone"] == "Pacific/Tahiti"
    assert [s["id"] for s in listed["items"]] == [created["id"]]

    # Not yet.
    assert await _run(db_session, at - timedelta(minutes=1)) == 0
    assert await _run(db_session, at) == 1
    # Claimed: a second worker at the same instant finds nothing.
    assert await _run(db_session, at) == 0

    [run] = await _runs(db_session, created["id"])
    assert run.status == "done" and run.created == 2
    run_id = run.id
    commands = await _commands(db_session, type="quick_scan")
    assert {c.machine_id for c in commands} == {a.id, b.id}
    assert all(c.created_by == "admin@test.local" for c in commands)
    assert {c.schedule_run_id for c in commands} == {run_id}
    # The default lifetime of a scheduled command: three hours.
    assert all(
        abs(c.expires_at - c.created_at - timedelta(minutes=180)) < timedelta(seconds=5)
        for c in commands
    )
    schedule = await _schedule(db_session, created["id"])
    assert schedule.state == "done" and schedule.next_run_at is None

    resp = await client.get(f"/api/v1/schedules/{created['id']}/runs", headers=headers)
    [out] = resp.json()["items"]
    assert out["created"] == 2 and out["status"] == "done"


async def test_weekly_moves_to_its_next_occurrence(client, db_session):
    headers, _ = await _admin(client, db_session)
    await machine(db_session, "PC-A")
    created = await _create(
        client,
        headers,
        {
            "name": "Mises à jour du mercredi",
            "command_type": "wu_scan",
            "target": {"kind": "all"},
            "recurrence": "weekly",
            "weekdays": [2],
            "time_of_day": "18:00",
        },
    )
    first = datetime.fromisoformat(created["next_run_at"])
    assert first.astimezone(TAHITI).weekday() == 2
    assert first.astimezone(TAHITI).time() == time(18, 0)
    assert await _run(db_session, first) == 1
    schedule = await _schedule(db_session, created["id"])
    assert schedule.state == "active"
    assert schedule.next_run_at == first + timedelta(days=7)


async def test_writing_is_refused_for_what_would_not_run(client, db_session):
    from app.features.setting.crud import set_value

    headers, _ = await _admin(client, db_session)
    tech, _ = await _tech(client, db_session)
    await machine(db_session, "PC-A")
    past = datetime.now(UTC) - timedelta(hours=1)
    resp = await client.post("/api/v1/schedules", headers=headers, json=_once(past))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "schedule.in_past"

    # Inside a forbidden window: a risky command, or a shutdown after.
    await set_value(
        db_session,
        windows.KEY_FORBIDDEN,
        [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "07:00", "end": "17:00"}],
        actor="test",
    )
    await db_session.commit()
    weekly = {
        "name": "Redémarrage",
        "command_type": "reboot",
        "target": {"kind": "all"},
        "recurrence": "weekly",
        "weekdays": [1],
        "time_of_day": "10:00",
    }
    resp = await client.post("/api/v1/schedules", headers=headers, json=weekly)
    assert resp.status_code == 409
    body = resp.json()["error"]
    assert body["code"] == "schedule.forbidden_window"
    assert body["details"]["window"]["start"] == "07:00"
    # The same at night, or an everyday command at 10:00, is fine.
    await _create(client, headers, {**weekly, "time_of_day": "20:00"})
    await _create(client, headers, {**weekly, "command_type": "quick_scan"})

    # A technician without schedule:write cannot plan at all; with it but
    # without the risky right, not a restart.
    resp = await client.post("/api/v1/schedules", headers=tech, json=weekly)
    assert resp.status_code == 403
    for bad in (
        {**weekly, "weekdays": []},
        {**weekly, "command_type": "package_install"},
        {**weekly, "shutdown_after": True},
        {**weekly, "command_type": "wake_on_lan", "wake_first": True},
    ):
        resp = await client.post("/api/v1/schedules", headers=headers, json=bad)
        assert resp.status_code == 422, bad


async def test_a_schedule_needs_the_right_to_run_what_it_carries(client, db_session):
    from app.features.user.permissions import ALL_PERMISSIONS

    await machine(db_session, "PC-A")
    planner = await group(
        db_session,
        "Planificateurs",
        {"schedule:read", "schedule:write", "command:execute", "machine:read"},
        None,
    )
    headers = await account(client, db_session, "plan@test.local", [planner.id])
    at = datetime.now(UTC) + timedelta(hours=2)
    resp = await client.post(
        "/api/v1/schedules", headers=headers, json=_once(at, command_type="reboot")
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["action"] == "execute"
    await _create(client, headers, _once(at))
    assert "schedule:write" in ALL_PERMISSIONS


# --- On whose behalf ----------------------------------------------------------


async def test_suspended_when_the_author_lost_a_right(client, db_session, monkeypatch):
    """Planning must not keep a right one has lost: the run does nothing, the
    schedule is suspended, the author told, the audit says why."""
    from app.features.audit.models import AuditEntry
    from app.features.notification.models import EmailOutbox
    from app.features.user import crud as user_crud
    from app.features.user.models import Group

    monkeypatch.setattr("app.core.config.settings.MAILGUN_API_KEY", "key")
    monkeypatch.setattr("app.core.config.settings.MAILGUN_DOMAIN", "mg.test")
    await machine(db_session, "PC-A")
    planners = await group(
        db_session,
        "Planificateurs",
        {
            "schedule:read",
            "schedule:write",
            "command:execute",
            "risky_command:execute",
            "machine:read",
        },
        None,
    )
    headers = await account(client, db_session, "plan@test.local", [planners.id])
    at = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    created = await _create(client, headers, _once(at, command_type="reboot"))

    g = await db_session.get(Group, planners.id)
    await user_crud.set_group_permissions(
        db_session, g, {"schedule:read", "schedule:write", "command:execute"}
    )
    await db_session.commit()

    assert await _run(db_session, at) == 1
    assert await _commands(db_session, type="reboot") == []
    [run] = await _runs(db_session, created["id"])
    assert run.status == "suspended"
    assert run.result_code == "permission_lost"
    assert run.result_params == {"permission": "risky_command:execute"}
    schedule = await _schedule(db_session, created["id"])
    assert schedule.state == "suspended"
    assert schedule.suspended_code == "permission_lost"
    [entry] = (
        await db_session.exec(
            select(AuditEntry).where(col(AuditEntry.action) == "schedule.suspend")
        )
    ).all()
    assert entry.details["cause"] == "permission_lost"
    [mail] = (
        await db_session.exec(
            select(EmailOutbox).where(col(EmailOutbox.to_address) == "plan@test.local")
        )
    ).all()
    assert "suspendue" in mail.subject
    assert "risky_command:execute" in mail.body


async def test_suspended_when_the_author_is_deactivated(client, db_session):
    from app.features.user.models import User

    headers, admin_id = await _admin(client, db_session)
    await machine(db_session, "PC-A")
    at = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    created = await _create(client, headers, _once(at))
    user = await db_session.get(User, uuid.UUID(admin_id))
    user.is_active = False
    db_session.add(user)
    await db_session.commit()
    await _run(db_session, at)
    schedule = await _schedule(db_session, created["id"])
    assert (schedule.state, schedule.suspended_code) == ("suspended", "author_inactive")
    assert await _commands(db_session, type="quick_scan") == []


async def test_turned_back_on_in_the_name_of_who_turns_it_on(client, db_session):
    headers, _ = await _admin(client, db_session)
    await machine(db_session, "PC-A")
    weekly = {
        "name": "Scan",
        "command_type": "quick_scan",
        "target": {"kind": "all"},
        "recurrence": "weekly",
        "weekdays": [0, 1, 2, 3, 4, 5, 6],
        "time_of_day": "19:00",
    }
    created = await _create(client, headers, weekly)
    url = f"/api/v1/schedules/{created['id']}/state"
    resp = await client.post(url, headers=headers, json={"enabled": False})
    assert resp.json()["state"] == "disabled" and resp.json()["next_run_at"] is None
    resp = await client.post(url, headers=headers, json={"enabled": True})
    assert resp.json()["state"] == "active" and resp.json()["next_run_at"]
    resp = await client.delete(f"/api/v1/schedules/{created['id']}", headers=headers)
    assert resp.status_code == 204
    resp = await client.get(f"/api/v1/schedules/{created['id']}", headers=headers)
    assert resp.status_code == 404


async def test_a_room_gone_suspends_and_a_late_occurrence_is_skipped(
    client, db_session
):
    from app.features.room.models import Room

    headers, _ = await _admin(client, db_session)
    resp = await client.post("/api/v1/rooms", headers=headers, json={"name": "A101"})
    room_id = resp.json()["id"]
    await machine(db_session, "PC-A", room_id=uuid.UUID(room_id))
    at = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    gone = await _create(
        client, headers, _once(at, target={"kind": "room", "value": room_id})
    )
    late = await _create(client, headers, _once(at))
    await db_session.delete(await db_session.get(Room, uuid.UUID(room_id)))
    await db_session.commit()

    # The worker was down for two hours.
    await _run(db_session, at + timedelta(hours=2))
    [run] = await _runs(db_session, gone["id"])
    assert run.status == "failed" and run.result_code == "missed"
    [run] = await _runs(db_session, late["id"])
    assert run.result_code == "missed"
    assert await _commands(db_session, type="quick_scan") == []

    # On time, the room gone: suspended.
    again = await _create(
        client,
        headers,
        _once(at + timedelta(hours=3), target={"kind": "all"}),
    )
    from app.features.schedule.models import Schedule

    row = await db_session.get(Schedule, uuid.UUID(again["id"]))
    row.target = {"kind": "room", "value": room_id}
    db_session.add(row)
    await db_session.commit()
    await _run(db_session, at + timedelta(hours=3))
    schedule = await _schedule(db_session, again["id"])
    assert schedule.suspended_code == "target_gone"


# --- Wake first, shut down after ------------------------------------------------


async def test_wake_first_then_shut_down_only_what_it_woke(
    client, db_session, monkeypatch
):
    from app.features.command.models import CommandStatus
    from app.features.machine.models import Machine
    from app.features.wol import dispatch as wol_dispatch
    from app.features.wol.sender import WakeOutcome

    async def sent(**_kw):
        return WakeOutcome(True, "Paquet émis", "wake.sent", {})

    monkeypatch.setattr(wol_dispatch, "emit_wake", sent)
    headers, _ = await _admin(client, db_session)
    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    long_ago = now - timedelta(days=1)
    asleep = await machine(
        db_session, "ASLEEP", last_seen=long_ago, mac_address="aa:bb:cc:dd:ee:01"
    )
    busy = await machine(
        db_session, "BUSY", last_seen=long_ago, mac_address="aa:bb:cc:dd:ee:02"
    )
    awake = await machine(db_session, "AWAKE", last_seen=now)
    created = await _create(
        client,
        headers,
        _once(
            now,
            command_type="wu_install",
            wake_first=True,
            shutdown_after=True,
            target={
                "kind": "machines",
                "machine_ids": [str(asleep.id), str(busy.id), str(awake.id)],
            },
        ),
    )
    await _run(db_session, now)
    [run] = await _runs(db_session, created["id"])
    assert run.status == "running"
    assert set(run.woken_ids) == {str(asleep.id), str(busy.id)}
    run_id = run.id
    wakes = await _commands(db_session, type="wake_on_lan")
    assert {w.schedule_run_id for w in wakes} == {run_id}
    installs = await _commands(db_session, type="wu_install")
    assert len(installs) == 3

    # The postes come up; one has somebody on it.
    for m in (asleep, busy):
        row = await db_session.get(Machine, m.id)
        row.last_seen = now + timedelta(minutes=20)
        row.session_user_present = m is busy
        db_session.add(row)
    for c in installs:
        c.status = CommandStatus.SUCCEEDED.value
        db_session.add(c)
    await db_session.commit()

    # Not in the ten minutes after a boot, whatever else.
    await _run(db_session, now + timedelta(minutes=5))
    assert await _commands(db_session, type="shutdown") == []

    await _run(db_session, now + timedelta(minutes=20))
    shutdowns = await _commands(db_session, type="shutdown")
    # The poste it woke and nobody uses; not the one with a session, not the
    # one that was already on.
    assert [s.machine_id for s in shutdowns] == [asleep.id]
    [run] = await _runs(db_session, created["id"])
    assert run.status == "done"
    assert run.kept_on_ids == [str(busy.id)]


async def test_a_scheduled_shutdown_leaves_a_session_alone(client, db_session):
    headers, _ = await _admin(client, db_session)
    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    free = await machine(db_session, "FREE", last_seen=now)
    await machine(db_session, "USED", last_seen=now, session_user_present=True)
    created = await _create(
        client, headers, _once(now, command_type="shutdown", name="Extinction du soir")
    )
    await _run(db_session, now)
    assert [c.machine_id for c in await _commands(db_session, type="shutdown")] == [
        free.id
    ]
    [run] = await _runs(db_session, created["id"])
    assert len(run.kept_on_ids) == 1


# --- Forbidden windows on the commands sent by hand ---------------------------


async def test_a_risky_command_to_several_postes_in_a_window_asks_first(
    client, db_session
):
    from app.features.setting.crud import set_value

    headers, _ = await _admin(client, db_session)
    a = await machine(db_session, "PC-A")
    b = await machine(db_session, "PC-B")
    await set_value(
        db_session,
        windows.KEY_FORBIDDEN,
        [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59"}],
        actor="test",
    )
    await db_session.commit()
    body = {"type": "reboot", "machine_ids": [str(a.id), str(b.id)]}
    resp = await client.post("/api/v1/commands", headers=headers, json=body)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "command.forbidden_window"
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={**body, "confirm_forbidden_window": True},
    )
    assert resp.status_code == 200 and resp.json()["count"] == 2
    # One poste is troubleshooting; an everyday command is not at risk.
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "shutdown", "machine_ids": [str(a.id)]},
    )
    assert resp.status_code == 200
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "machine_ids": [str(a.id), str(b.id)]},
    )
    assert resp.status_code == 200


async def test_commands_aim_at_a_room_or_a_building(client, db_session):
    headers, _ = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/buildings", headers=headers, json={"name": "Bât. A"}
    )
    building = resp.json()["id"]
    resp = await client.post(
        "/api/v1/rooms", headers=headers, json={"name": "A101", "building_id": building}
    )
    room = resp.json()["id"]
    inside = await machine(db_session, "IN", room_id=uuid.UUID(room))
    await machine(db_session, "OUT")
    for key, value in (("target_room_id", room), ("target_building_id", building)):
        resp = await client.post(
            "/api/v1/commands",
            headers=headers,
            json={"type": "quick_scan", key: value},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] in (0, 1)
    rows = await _commands(db_session, type="quick_scan")
    assert {c.machine_id for c in rows} == {inside.id}
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "target_room_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404


# --- Settings -----------------------------------------------------------------


async def test_settings_zone_and_windows(client, db_session):
    headers, _ = await _admin(client, db_session)
    body = (await client.get("/api/v1/settings", headers=headers)).json()
    assert body["console_timezone"] == "Pacific/Tahiti"
    assert body["forbidden_windows"] == []
    resp = await client.patch(
        "/api/v1/settings",
        headers=headers,
        json={
            "console_timezone": "Europe/Paris",
            "forbidden_windows": [
                {"days": [4, 0, 0], "start": "08:00", "end": "12:00"}
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["console_timezone"] == "Europe/Paris"
    assert body["forbidden_windows"] == [
        {"days": [0, 4], "start": "08:00", "end": "12:00"}
    ]
    for bad in (
        {"console_timezone": "Mars/Olympus"},
        {"forbidden_windows": [{"days": [0], "start": "12:00", "end": "08:00"}]},
        {"forbidden_windows": [{"days": [9], "start": "08:00", "end": "12:00"}]},
    ):
        resp = await client.patch("/api/v1/settings", headers=headers, json=bad)
        assert resp.status_code == 422, bad
    entries = (
        await client.get(
            "/api/v1/audit", headers=headers, params={"action": "settings.update"}
        )
    ).json()["items"]
    assert entries[0]["details"]["forbidden_windows"] == "0,4 08:00–12:00"


# --- Rings ----------------------------------------------------------------------


async def _two_rooms(client, headers, db_session):
    rooms = []
    for name in ("PILOTE", "PARC"):
        resp = await client.post("/api/v1/rooms", headers=headers, json={"name": name})
        rooms.append(resp.json()["id"])
    for i, room in enumerate(rooms):
        for n in range(2):
            await machine(db_session, f"{i}-{n}", room_id=uuid.UUID(room))
    return rooms


def _ringed(at, rooms, **fields):
    return _once(
        at,
        name="Mises à jour par étapes",
        command_type="wu_install",
        target={"kind": "room", "value": rooms[0]},
        rings=[
            {"target": {"kind": "room", "value": rooms[0]}},
            {"target": {"kind": "room", "value": rooms[1]}},
        ],
        ring_observe_hours=2,
        ring_failure_percent=20,
        **fields,
    )


async def _finish(db_session, run_id, statuses):
    from app.features.command.models import Command

    db_session.expire_all()
    rows = (
        await db_session.exec(
            select(Command)
            .where(col(Command.schedule_run_id) == run_id)
            .order_by(col(Command.machine_id))
        )
    ).all()
    for row, status in zip(rows, statuses, strict=False):
        row.status = status
        db_session.add(row)
    await db_session.commit()


async def test_rings_go_on_under_the_threshold(client, db_session):
    headers, _ = await _admin(client, db_session)
    rooms = await _two_rooms(client, headers, db_session)
    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    created = await _create(client, headers, _ringed(now, rooms))
    await _run(db_session, now)
    [run] = await _runs(db_session, created["id"])
    assert run.status == "running" and run.stage == 0 and run.created == 2

    await _finish(db_session, run.id, ["succeeded", "succeeded"])
    # Observed for less than its delay: the pilot alone.
    await _run(db_session, now + timedelta(hours=1))
    assert len(await _commands(db_session, type="wu_install")) == 2
    await _run(db_session, now + timedelta(hours=2))
    [run] = await _runs(db_session, created["id"])
    assert run.stage == 1 and run.created == 4
    assert run.status == "done"
    stages = {c.schedule_stage for c in await _commands(db_session, type="wu_install")}
    assert stages == {0, 1}


async def test_rings_halt_above_the_threshold_and_tell_the_author(
    client, db_session, monkeypatch
):
    from app.features.audit.models import AuditEntry
    from app.features.notification.models import EmailOutbox

    monkeypatch.setattr("app.core.config.settings.MAILGUN_API_KEY", "key")
    monkeypatch.setattr("app.core.config.settings.MAILGUN_DOMAIN", "mg.test")
    headers, _ = await _admin(client, db_session)
    rooms = await _two_rooms(client, headers, db_session)
    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    created = await _create(client, headers, _ringed(now, rooms))
    await _run(db_session, now)
    [run] = await _runs(db_session, created["id"])
    await _finish(db_session, run.id, ["failed", "succeeded"])
    await _run(db_session, now + timedelta(hours=2))
    [run] = await _runs(db_session, created["id"])
    assert run.status == "halted" and run.result_code == "ring_failed"
    assert run.result_params["percent"] == 50
    assert len(await _commands(db_session, type="wu_install")) == 2
    [entry] = (
        await db_session.exec(
            select(AuditEntry).where(col(AuditEntry.action) == "schedule.halt")
        )
    ).all()
    assert entry.details["stage"] == 1
    [mail] = (await db_session.exec(select(EmailOutbox))).all()
    assert "arrêté" in mail.subject and "50 %" in mail.body


async def test_rings_halt_when_the_pilot_never_answered(client, db_session):
    headers, _ = await _admin(client, db_session)
    rooms = await _two_rooms(client, headers, db_session)
    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    created = await _create(client, headers, _ringed(now, rooms))
    await _run(db_session, now)
    await _run(db_session, now + timedelta(hours=3))
    [run] = await _runs(db_session, created["id"])
    assert (run.status, run.result_code) == ("halted", "ring_no_result")


async def test_rings_are_for_installs(client, db_session):
    headers, _ = await _admin(client, db_session)
    rooms = await _two_rooms(client, headers, db_session)
    at = datetime.now(UTC) + timedelta(hours=1)
    resp = await client.post(
        "/api/v1/schedules",
        headers=headers,
        json=_ringed(at, rooms, **{}) | {"command_type": "quick_scan"},
    )
    assert resp.status_code == 422


# --- Scope and merge ---------------------------------------------------------------


async def test_a_restricted_reader_sees_what_concerns_its_scope(client, db_session):
    sites = await two_sites(client, db_session)
    at = datetime.now(UTC) + timedelta(hours=1)
    parc = await _create(client, sites.admin, _once(at))
    mine = await _create(
        client,
        sites.scoped,
        _once(at, target={"kind": "machines", "machine_ids": [str(sites.a.id)]}),
    )
    on_b = await _create(
        client,
        sites.admin,
        _once(at, target={"kind": "machines", "machine_ids": [str(sites.b.id)]}),
    )
    listed = (await client.get("/api/v1/schedules", headers=sites.scoped)).json()
    assert [s["id"] for s in listed["items"]] == [mine["id"]]
    for other in (parc, on_b):
        resp = await client.get(
            f"/api/v1/schedules/{other['id']}", headers=sites.scoped
        )
        assert resp.status_code == 404
    # Nor may it aim at the other site's poste.
    resp = await client.post(
        "/api/v1/schedules",
        headers=sites.scoped,
        json=_once(at, target={"kind": "machines", "machine_ids": [str(sites.b.id)]}),
    )
    assert resp.status_code == 404
    assert SITE_A


async def test_a_merge_aims_the_schedule_at_the_kept_poste(client, db_session):
    from app.features.machine import crud as machine_crud
    from app.features.machine.models import Machine

    headers, _ = await _admin(client, db_session)
    dup = await machine(db_session, "DUP")
    kept = await machine(db_session, "KEPT")
    at = datetime.now(UTC) + timedelta(hours=1)
    created = await _create(
        client,
        headers,
        _once(
            at, target={"kind": "machines", "machine_ids": [str(dup.id), str(kept.id)]}
        ),
    )
    await machine_crud.merge_into(
        db_session,
        target=await db_session.get(Machine, kept.id),
        source=await db_session.get(Machine, dup.id),
    )
    await db_session.commit()
    schedule = await _schedule(db_session, created["id"])
    assert schedule.target["machine_ids"] == [str(kept.id)]


def test_today_is_a_date():
    assert isinstance(date.today(), date)


@pytest.fixture(autouse=True)
def _tahiti(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.CONSOLE_TIMEZONE", "Pacific/Tahiti")


# --- Relecture de C3 -----------------------------------------------------------


def _wake_sent(monkeypatch):
    from app.features.wol import dispatch as wol_dispatch
    from app.features.wol.sender import WakeOutcome

    async def sent(**_kw):
        return WakeOutcome(True, "ok", "wake.sent", {})

    monkeypatch.setattr(wol_dispatch, "emit_wake", sent)


async def test_shutdown_after_waits_for_a_command_still_running_past_its_ttl(
    client, db_session, monkeypatch
):
    """``expires_at`` governs a command still waiting, not one at work: an
    installation running after the TTL is not cut by the shutdown."""
    from app.features.command.models import CommandStatus
    from app.features.machine.models import Machine

    _wake_sent(monkeypatch)
    headers, _ = await _admin(client, db_session)
    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=2)
    m = await machine(
        db_session,
        "ASLEEP",
        last_seen=now - timedelta(days=1),
        mac_address="aa:bb:cc:dd:ee:01",
    )
    await _create(
        client,
        headers,
        _once(
            now,
            command_type="wu_install_full",
            wake_first=True,
            shutdown_after=True,
            ttl_minutes=10,
            target={"kind": "machines", "machine_ids": [str(m.id)]},
        ),
    )
    await _run(db_session, now)
    [c] = await _commands(db_session, type="wu_install_full")
    c.status = CommandStatus.RUNNING.value
    db_session.add(c)
    row = await db_session.get(Machine, m.id)
    row.last_seen = now + timedelta(minutes=20)
    row.session_user_present = False
    db_session.add(row)
    await db_session.commit()
    await _run(db_session, now + timedelta(minutes=20))
    assert await _commands(db_session, type="shutdown") == []

    # Done: the poste is shut down at the next pass.
    [c] = await _commands(db_session, type="wu_install_full")
    c.status = CommandStatus.SUCCEEDED.value
    db_session.add(c)
    row = await db_session.get(Machine, m.id)
    row.last_seen = now + timedelta(minutes=25)
    db_session.add(row)
    await db_session.commit()
    await _run(db_session, now + timedelta(minutes=25))
    assert len(await _commands(db_session, type="shutdown")) == 1


async def test_a_later_ring_is_not_shut_down_under_its_running_command(
    client, db_session, monkeypatch
):
    """The patience for a stage counts from its own wake, not from the start
    of the run, hours earlier."""
    from app.features.command.models import Command, CommandStatus
    from app.features.machine.models import Machine

    _wake_sent(monkeypatch)
    headers, _ = await _admin(client, db_session)
    rooms = []
    for name in ("PILOTE", "PARC"):
        resp = await client.post("/api/v1/rooms", headers=headers, json={"name": name})
        rooms.append(resp.json()["id"])
    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=2)
    await machine(db_session, "P0", room_id=uuid.UUID(rooms[0]), last_seen=now)
    late = await machine(
        db_session,
        "F0",
        room_id=uuid.UUID(rooms[1]),
        last_seen=now - timedelta(days=1),
        mac_address="aa:bb:cc:dd:ee:09",
    )
    payload = _ringed(now, rooms, wake_first=True, shutdown_after=True)
    payload["ring_observe_hours"] = 5
    created = await _create(client, headers, payload)
    await _run(db_session, now)
    [run] = await _runs(db_session, created["id"])
    await _finish(db_session, run.id, ["succeeded"])
    t2 = now + timedelta(hours=5)
    await _run(db_session, t2)
    [run] = await _runs(db_session, created["id"])
    assert run.stage == 1 and run.woken_ids == [str(late.id)]
    rows = (
        await db_session.exec(select(Command).where(col(Command.schedule_stage) == 1))
    ).all()
    for r in rows:
        r.status = CommandStatus.RUNNING.value
        db_session.add(r)
    row = await db_session.get(Machine, late.id)
    row.last_seen = t2 + timedelta(minutes=20)
    row.session_user_present = False
    db_session.add(row)
    await db_session.commit()
    await _run(db_session, t2 + timedelta(minutes=20))
    assert await _commands(db_session, type="shutdown") == []


async def test_disabling_a_schedule_stops_its_rings(client, db_session):
    headers, _ = await _admin(client, db_session)
    rooms = await _two_rooms(client, headers, db_session)
    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    created = await _create(client, headers, _ringed(now, rooms))
    await _run(db_session, now)
    [run] = await _runs(db_session, created["id"])
    run_id = run.id
    first = len(await _commands(db_session, type="wu_install"))
    await _finish(db_session, run_id, ["succeeded"] * first)
    resp = await client.post(
        f"/api/v1/schedules/{created['id']}/state",
        headers=headers,
        json={"enabled": False},
    )
    assert resp.status_code == 200, resp.text
    await _run(db_session, now + timedelta(hours=30))
    assert len(await _commands(db_session, type="wu_install")) == first
    [run] = await _runs(db_session, created["id"])
    assert (run.status, run.result_code) == ("halted", "schedule_disabled")


async def test_a_stage_that_reached_no_poste_does_not_open_the_next(client, db_session):
    """An empty pilot room observed nothing: the parc is not next."""
    headers, _ = await _admin(client, db_session)
    rooms = []
    for name in ("VIDE", "PARC"):
        resp = await client.post("/api/v1/rooms", headers=headers, json={"name": name})
        rooms.append(resp.json()["id"])
    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    await machine(db_session, "F0", room_id=uuid.UUID(rooms[1]), last_seen=now)
    created = await _create(client, headers, _ringed(now, rooms))
    await _run(db_session, now)
    await _run(db_session, now + timedelta(hours=30))
    assert await _commands(db_session, type="wu_install") == []
    [run] = await _runs(db_session, created["id"])
    assert (run.status, run.result_code) == ("halted", "ring_no_result")


async def test_one_schedule_that_raises_does_not_block_the_others(
    client, db_session, monkeypatch
):
    from app.features.schedule import runner

    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-1")
    now = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=2)
    target = {"kind": "machines", "machine_ids": [str(m.id)]}
    bad = await _create(client, headers, _once(now, name="casse", target=target))
    good = await _create(
        client,
        headers,
        _once(now + timedelta(seconds=30), name="saine", target=target),
    )
    real = runner.run_stage

    async def boom(session, schedule, *args, **kwargs):
        if str(schedule.id) == bad["id"]:
            raise RuntimeError("boom")
        return await real(session, schedule, *args, **kwargs)

    monkeypatch.setattr(runner, "run_stage", boom)
    await _run(db_session, now + timedelta(minutes=1))
    [failed] = await _runs(db_session, bad["id"])
    assert (failed.status, failed.result_code) == ("failed", "internal_error")
    [ran] = await _runs(db_session, good["id"])
    assert ran.status == "done"
    # Not picked again at the next pass.
    await _run(db_session, now + timedelta(minutes=2))
    assert len(await _runs(db_session, bad["id"])) == 1


async def test_a_zone_change_keeps_the_planned_hour(client, db_session):
    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-1")
    target = {"kind": "machines", "machine_ids": [str(m.id)]}
    created = await _create(
        client,
        headers,
        {
            "name": "hebdo",
            "command_type": "quick_scan",
            "target": target,
            "recurrence": "weekly",
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "time_of_day": "18:00",
        },
    )
    before = (await _schedule(db_session, created["id"])).next_run_at
    assert before.astimezone(TAHITI).strftime("%H:%M") == "18:00"
    resp = await client.patch(
        "/api/v1/settings", headers=headers, json={"console_timezone": "Europe/Paris"}
    )
    assert resp.status_code == 200, resp.text
    row = await _schedule(db_session, created["id"])
    await db_session.refresh(row)
    assert row.next_run_at.astimezone(ZoneInfo("Europe/Paris")).strftime("%H:%M") == (
        "18:00"
    )
    listed = (await client.get("/api/v1/schedules", headers=headers)).json()
    assert listed["items"][0]["next_run_local"].endswith("T18:00")
