"""Alerts: the Windows support table (pure) and the worker's evaluation
(require TIAI_TEST_DATABASE_URL): opening, refreshing, resolving, the rules
turned off, the verifications opened, the merge and the purge."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlmodel import col, select

from app.features.alert.os_support import Channel, channel_of, support_of

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


# --- Windows support table ---------------------------------------------------


@pytest.mark.parametrize(
    ("os_version", "end", "ended"),
    [
        ("Windows 11 Pro 23H2 (Build 22631)", date(2025, 11, 11), True),
        # Same build, longer servicing on the Education channel.
        ("Windows 11 Education 23H2 (Build 22631)", date(2026, 11, 10), True),
        ("Windows 11 Enterprise 24H2 (Build 26100)", date(2027, 10, 12), False),
        ("Windows 11 Pro 25H2 (Build 26200)", date(2027, 10, 12), False),
        ("Windows 10 Pro 22H2 (Build 19045)", date(2025, 10, 14), True),
        ("Windows 10 Enterprise LTSC 2021 (Build 19044)", date(2027, 1, 12), False),
        ("Windows 10 Enterprise LTSC 2019 (Build 17763)", date(2029, 1, 9), False),
        ("Windows 11 Enterprise LTSC 2024 (Build 26100)", date(2029, 10, 9), False),
        # IoT Enterprise LTSC: ten years since 2021, the Enterprise date before.
        (
            "Windows 11 IoT Enterprise LTSC 2024 (Build 26100)",
            date(2034, 10, 10),
            False,
        ),
        ("Windows 10 IoT Enterprise LTSC 2021 (Build 19044)", date(2032, 1, 13), False),
        ("Windows 10 IoT Enterprise LTSC 2019 (Build 17763)", date(2029, 1, 9), False),
        # Pro Education goes with Home and Pro, not with Education.
        ("Windows 11 Pro Education 24H2 (Build 26100)", date(2026, 10, 13), True),
        ("Windows 11 Pro Education 23H2 (Build 22631)", date(2025, 11, 11), True),
        (
            "Windows 11 Pro for Workstations 25H2 (Build 26200)",
            date(2027, 10, 12),
            False,
        ),
        ("Windows 7 Professional (Build 7601)", date(2020, 1, 14), True),
    ],
)
def test_support_dates(os_version, end, ended):
    support = support_of(os_version)
    assert support is not None
    assert support.end == end
    assert support.ended(TODAY) is ended


def test_old_general_windows_10_is_ended_without_a_date():
    # 1607 on a Pro poste: only the LTSB of that build is still listed.
    support = support_of("Windows 10 Pro 1607 (Build 14393)")
    assert support is not None and support.end is None
    assert support.ended(TODAY)


@pytest.mark.parametrize(
    "os_version",
    [
        None,
        "",
        "Windows Server 2022 Standard (Build 20348)",
        "Windows 11 Pro 26H2 (Build 28000)",  # newer than the table
        "Windows 11 Pro",  # no build
        "linux",
    ],
)
def test_unknown_is_never_unsupported(os_version):
    assert support_of(os_version) is None


def test_channels():
    assert channel_of("Windows 11 Pro Education") is Channel.HOME_PRO
    assert channel_of("Windows 11 Pro for Workstations") is Channel.HOME_PRO
    assert channel_of("Windows 11 Education") is Channel.ENTERPRISE_EDUCATION
    assert channel_of("Windows 10 IoT Enterprise LTSC 2021") is Channel.IOT_LTSC
    assert channel_of("Windows 10 Enterprise LTSB 2016") is Channel.LTSC
    assert channel_of("Windows 11 Famille") is Channel.HOME_PRO


# --- Evaluation --------------------------------------------------------------


async def _machine(db_session, hostname="PC-1", **fields):
    from app.features.machine.models import Machine

    fields.setdefault("last_seen", NOW)
    fields.setdefault("first_seen", NOW - timedelta(days=90))
    machine = Machine(machine_uuid=str(uuid.uuid4()), hostname=hostname, **fields)
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)
    return machine.id


async def _evaluate(db_session, now=NOW):
    from app.features.alert import crud

    result = await crud.evaluate(db_session, now)
    await db_session.commit()
    return result


async def _alerts(db_session, machine_id=None, *, open_only=False):
    from app.features.alert.models import MachineAlert

    db_session.expire_all()
    stmt = select(MachineAlert)
    if machine_id is not None:
        stmt = stmt.where(col(MachineAlert.machine_id) == machine_id)
    if open_only:
        stmt = stmt.where(col(MachineAlert.resolved_at).is_(None))
    return list((await db_session.exec(stmt)).all())


async def _set(db_session, key, value):
    from app.features.setting import crud

    await crud.set_value(db_session, key, value, actor="test")
    await db_session.commit()


async def test_disk_low_opens_refreshes_and_resolves(db_session):
    from app.features.machine.models import Machine

    mid = await _machine(
        db_session, system_volume_total_mb=100_000, system_volume_free_mb=5_000
    )
    result = await _evaluate(db_session)
    assert [(a.machine_id, a.rule) for a in result.opened] == [(mid, "disk_low")]
    [alert] = await _alerts(db_session, mid)
    assert alert.detail == {
        "free_percent": 5.0,
        "free_mb": 5_000,
        "threshold_percent": 10,
    }
    opened_at = alert.opened_at

    # Still holding, a new figure: the same alert, refreshed.
    machine = await db_session.get(Machine, mid)
    machine.system_volume_free_mb = 4_000
    db_session.add(machine)
    await db_session.commit()
    result = await _evaluate(db_session)
    assert result.opened == [] and result.refreshed == 1
    [alert] = await _alerts(db_session, mid)
    assert alert.detail["free_percent"] == 4.0
    assert alert.opened_at == opened_at

    # Running again with nothing changed changes nothing.
    result = await _evaluate(db_session)
    assert (result.opened, result.refreshed, result.resolved) == ([], 0, 0)

    # Space freed: resolved, kept as history.
    machine = await db_session.get(Machine, mid)
    machine.system_volume_free_mb = 50_000
    db_session.add(machine)
    await db_session.commit()
    result = await _evaluate(db_session)
    assert result.resolved == 1
    [alert] = await _alerts(db_session, mid)
    assert alert.resolved_at is not None

    # Full again: a new alert, the old one stays resolved.
    machine = await db_session.get(Machine, mid)
    machine.system_volume_free_mb = 1_000
    db_session.add(machine)
    await db_session.commit()
    await _evaluate(db_session)
    alerts = await _alerts(db_session, mid)
    assert len(alerts) == 2
    assert len([a for a in alerts if a.resolved_at is None]) == 1


async def test_rule_turned_off_resolves_its_alerts(db_session):
    from app.features.setting.crud import KEY_ALERT_RULES

    mid = await _machine(
        db_session, system_volume_total_mb=100_000, system_volume_free_mb=1_000
    )
    await _evaluate(db_session)
    assert len(await _alerts(db_session, mid, open_only=True)) == 1
    await _set(db_session, KEY_ALERT_RULES, ["inactive"])
    result = await _evaluate(db_session)
    assert result.resolved == 1
    assert await _alerts(db_session, mid, open_only=True) == []


async def test_disk_unhealthy_ignores_healthy_unread_and_removable(db_session):
    from app.features.inventory.models import Disk

    sick = await _machine(db_session, "SICK")
    fine = await _machine(db_session, "FINE")
    for machine_id, device, health, removable in [
        (sick, "0", "Warning", False),
        (sick, "1", "Healthy", False),
        (fine, "0", "Healthy", False),
        (fine, "1", None, False),
        (fine, "2", "Unhealthy", True),
    ]:
        db_session.add(
            Disk(
                machine_id=machine_id,
                device_id=device,
                model=f"Disk {device}",
                health_status=health,
                is_removable=removable,
            )
        )
    await db_session.commit()
    await _evaluate(db_session)
    [alert] = await _alerts(db_session)
    assert alert.machine_id == sick and alert.rule == "disk_unhealthy"
    assert alert.detail == {"disks": [{"model": "Disk 0", "health": "Warning"}]}


async def test_unencrypted_volume_scope(db_session):
    from app.features.inventory.models import Volume
    from app.features.setting.crud import KEY_ALERT_UNENCRYPTED_SCOPE

    laptop = await _machine(db_session, "LAPTOP", hw_chassis_type="laptop")
    desktop = await _machine(db_session, "DESKTOP", hw_chassis_type="desktop")
    unread = await _machine(db_session, "UNREAD", hw_chassis_type="laptop")
    for machine_id, status in [
        (laptop, "FullyDecrypted"),
        (desktop, "FullyDecrypted"),
        (unread, None),
    ]:
        db_session.add(
            Volume(
                machine_id=machine_id,
                letter="C:",
                is_system=True,
                encryption_status=status,
            )
        )
    await db_session.commit()
    await _evaluate(db_session)
    assert {a.machine_id for a in await _alerts(db_session, open_only=True)} == {laptop}

    await _set(db_session, KEY_ALERT_UNENCRYPTED_SCOPE, "all")
    await _evaluate(db_session)
    assert {a.machine_id for a in await _alerts(db_session, open_only=True)} == {
        laptop,
        desktop,
    }


async def test_reboot_pending_counts_from_since(db_session):
    old = await _machine(
        db_session,
        "OLD",
        wu_reboot_required=True,
        wu_reboot_required_since=NOW - timedelta(days=8),
    )
    await _machine(
        db_session,
        "RECENT",
        wu_reboot_required=True,
        wu_reboot_required_since=NOW - timedelta(days=2),
    )
    await _evaluate(db_session)
    [alert] = await _alerts(db_session, open_only=True)
    assert alert.machine_id == old and alert.rule == "reboot_pending"
    assert alert.detail["threshold_days"] == 7


async def test_os_unsupported_and_inactive(db_session):
    ended = await _machine(
        db_session, "W10", os_version="Windows 10 Pro 22H2 (Build 19045)"
    )
    await _machine(db_session, "W11", os_version="Windows 11 Pro 25H2 (Build 26200)")
    gone = await _machine(db_session, "GONE", last_seen=NOW - timedelta(days=45))
    await _evaluate(db_session)
    found = {(a.machine_id, a.rule): a.detail for a in await _alerts(db_session)}
    assert found[(ended, "os_unsupported")] == {
        "os_version": "Windows 10 Pro 22H2 (Build 19045)",
        "end_of_support": "2025-10-14",
    }
    assert (gone, "inactive") in found
    assert len(found) == 2


async def test_forbidden_software(db_session):
    from app.features.inventory.models import MachineSoftware, Software
    from app.features.setting.crud import KEY_ALERT_FORBIDDEN

    mid = await _machine(db_session)
    other = await _machine(db_session, "PC-2")
    programs = [
        Software(name="uTorrent", version="3.6", publisher="BitTorrent"),
        Software(name="Firefox", version="120", publisher="Mozilla"),
        Software(name="100% Free Tool", version="", publisher=""),
    ]
    for program in programs:
        db_session.add(program)
    await db_session.commit()
    for program in programs:
        await db_session.refresh(program)
    db_session.add(MachineSoftware(machine_id=mid, software_id=programs[0].id))
    db_session.add(MachineSoftware(machine_id=other, software_id=programs[1].id))
    db_session.add(MachineSoftware(machine_id=other, software_id=programs[2].id))
    await db_session.commit()

    # No list, no rule.
    await _evaluate(db_session)
    assert await _alerts(db_session) == []

    # « % » is a character, not a wildcard: « 0% » does not match Firefox.
    await _set(db_session, KEY_ALERT_FORBIDDEN, ["torrent", "0% "])
    await _evaluate(db_session)
    found = {a.machine_id: a.detail for a in await _alerts(db_session)}
    assert found[mid] == {
        "programs": [{"name": "uTorrent", "version": "3.6"}],
        "count": 1,
    }
    assert found[other]["programs"] == [{"name": "100% Free Tool", "version": None}]


async def test_auto_check_opens_one_verification(db_session):
    from app.features.check.models import MachineCheck
    from app.features.setting.crud import KEY_ALERT_AUTO_CHECK

    await _set(db_session, KEY_ALERT_AUTO_CHECK, ["disk_low"])
    mid = await _machine(
        db_session, system_volume_total_mb=100_000, system_volume_free_mb=1_000
    )
    asked = await _machine(
        db_session, "ASKED", system_volume_total_mb=100_000, system_volume_free_mb=1_000
    )
    db_session.add(MachineCheck(machine_id=asked, requested_by="someone@test.local"))
    await db_session.commit()

    result = await _evaluate(db_session)
    assert result.checks_opened == 1
    checks = (
        await db_session.exec(
            select(MachineCheck).where(col(MachineCheck.machine_id) == mid)
        )
    ).all()
    [check] = checks
    check_id = check.id
    assert check.instructions_code == "alert.disk_low"
    assert check.instructions_params["free_percent"] == 1.0
    assert check.instructions.startswith("Alerte : Il reste 1.0 %")
    [alert] = await _alerts(db_session, mid)
    assert alert.check_id == check_id
    # The poste already asked about keeps its one request.
    [kept] = await _alerts(db_session, asked)
    assert kept.check_id is None


async def test_large_evaluation_is_inserted_in_chunks(db_session, monkeypatch):
    """Every row opened and every verification bound, across several INSERTs
    (PostgreSQL refuses a statement past 65,535 parameters)."""
    from app.features.alert import crud
    from app.features.check.models import MachineCheck
    from app.features.setting.crud import KEY_ALERT_AUTO_CHECK

    monkeypatch.setattr(crud, "CHUNK", 2)
    await _set(db_session, KEY_ALERT_AUTO_CHECK, ["inactive"])
    ids = [
        await _machine(db_session, f"GONE-{i}", last_seen=NOW - timedelta(days=45))
        for i in range(5)
    ]
    result = await _evaluate(db_session)
    assert len(result.opened) == 5
    assert result.checks_opened == 5
    alerts = await _alerts(db_session, open_only=True)
    assert {a.machine_id for a in alerts} == set(ids)
    checks = (await db_session.exec(select(MachineCheck))).all()
    assert {a.check_id for a in alerts} == {c.id for c in checks}
    # Run again: nothing new.
    again = await _evaluate(db_session)
    assert again.opened == [] and again.checks_opened == 0


async def test_merge_moves_history_and_drops_open(db_session):
    from app.features.machine import crud as machine_crud
    from app.features.machine.models import Machine

    source = await _machine(
        db_session, "DUP", system_volume_total_mb=100_000, system_volume_free_mb=1_000
    )
    target = await _machine(
        db_session, "KEPT", system_volume_total_mb=100_000, system_volume_free_mb=1_000
    )
    await _evaluate(db_session)
    # One resolved alert on the duplicate, then a new open one.
    machine = await db_session.get(Machine, source)
    machine.system_volume_free_mb = 90_000
    db_session.add(machine)
    await db_session.commit()
    await _evaluate(db_session)
    machine = await db_session.get(Machine, source)
    machine.system_volume_free_mb = 1_000
    db_session.add(machine)
    await db_session.commit()
    await _evaluate(db_session)

    await machine_crud.merge_into(
        db_session,
        target=await db_session.get(Machine, target),
        source=await db_session.get(Machine, source),
    )
    await db_session.commit()
    alerts = await _alerts(db_session, target)
    assert len(alerts) == 2
    assert len([a for a in alerts if a.resolved_at is None]) == 1


async def test_purge_keeps_open_alerts(db_session):
    from app.features.alert import crud
    from app.features.alert.models import MachineAlert

    mid = await _machine(db_session)
    db_session.add(
        MachineAlert(
            machine_id=mid,
            rule="disk_low",
            opened_at=NOW - timedelta(days=900),
            resolved_at=NOW - timedelta(days=800),
        )
    )
    db_session.add(
        MachineAlert(
            machine_id=mid, rule="inactive", opened_at=NOW - timedelta(days=900)
        )
    )
    await db_session.commit()
    assert await crud.purge_before(db_session, NOW - timedelta(days=400)) == 1
    [left] = await _alerts(db_session)
    assert left.rule == "inactive"


async def test_heartbeat_dates_the_pending_reboot(client, db_session):
    from app.features.machine.models import Machine
    from tests.test_api_console import _enroll, _heartbeat

    enrolled = await _enroll(client, str(uuid.uuid4()))

    async def beat(reboot):
        resp = await _heartbeat(
            client,
            enrolled["token"],
            windows_update={"reboot_required": reboot, "pending": []},
        )
        assert resp.status_code == 200, resp.text
        db_session.expire_all()
        return await db_session.get(Machine, uuid.UUID(enrolled["machine_id"]))

    machine = await beat(True)
    since = machine.wu_reboot_required_since
    assert since is not None
    machine = await beat(True)
    assert machine.wu_reboot_required_since == since
    machine = await beat(False)
    assert machine.wu_reboot_required_since is None
