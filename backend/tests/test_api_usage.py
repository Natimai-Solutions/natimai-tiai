"""Usage counters fed by the heartbeat (require TIAI_TEST_DATABASE_URL).

The clock is moved by writing ``last_seen`` straight into the database and by
pinning the heartbeat handler's ``utcnow`` — never by sleeping.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import col, select

from tests.test_api_console import _admin_headers, _enroll, _heartbeat

# A fixed instant in the recent past, well inside an hour: every credit below
# is then exact to the second.
NOW = datetime.now(UTC).replace(minute=30, second=0, microsecond=0) - timedelta(hours=2)


async def _set_last_seen(db_session, machine_id: str, when: datetime) -> None:
    from app.features.machine.models import Machine

    machine = await db_session.get(Machine, uuid.UUID(machine_id))
    machine.last_seen = when
    db_session.add(machine)
    await db_session.commit()


async def _hours(db_session, machine_id: str) -> list[tuple[datetime, int]]:
    """The poste's buckets, oldest first — as tuples, never cached entities."""
    from app.features.usage.models import MachineUptime

    rows = await db_session.exec(
        select(MachineUptime.hour, MachineUptime.seconds_on)
        .where(col(MachineUptime.machine_id) == uuid.UUID(machine_id))
        .order_by(col(MachineUptime.hour))
    )
    return [(hour, seconds) for hour, seconds in rows.all()]


def _pin_clock(monkeypatch, instant: datetime) -> None:
    from app.api.routes import agent

    monkeypatch.setattr(agent, "utcnow", lambda: instant)


async def test_close_heartbeats_credit_the_gap(client, db_session, monkeypatch):
    enrolled = await _enroll(client, "usage-close")
    await _set_last_seen(
        db_session, enrolled["machine_id"], NOW - timedelta(seconds=61)
    )
    _pin_clock(monkeypatch, NOW)

    assert (await _heartbeat(client, enrolled["token"])).status_code == 200

    hour = NOW.replace(minute=0)
    assert await _hours(db_session, enrolled["machine_id"]) == [(hour, 61)]

    # The next beat adds to the same hour rather than replacing it.
    _pin_clock(monkeypatch, NOW + timedelta(seconds=60))
    await _heartbeat(client, enrolled["token"])
    assert await _hours(db_session, enrolled["machine_id"]) == [(hour, 121)]


async def test_a_heartbeat_after_a_hole_credits_nothing(
    client, db_session, monkeypatch
):
    from app.core.config import settings

    enrolled = await _enroll(client, "usage-hole")
    # Off overnight: the morning's first heartbeat proves nothing about the
    # night, and the poste's last_seen still moves on.
    await _set_last_seen(
        db_session,
        enrolled["machine_id"],
        NOW - timedelta(seconds=settings.OFFLINE_AFTER_SECONDS),
    )
    _pin_clock(monkeypatch, NOW)

    assert (await _heartbeat(client, enrolled["token"])).status_code == 200
    assert await _hours(db_session, enrolled["machine_id"]) == []


async def test_a_gap_across_the_hour_writes_two_buckets(
    client, db_session, monkeypatch
):
    enrolled = await _enroll(client, "usage-straddle")
    hour = NOW.replace(minute=0)
    await _set_last_seen(
        db_session, enrolled["machine_id"], hour - timedelta(seconds=20)
    )
    _pin_clock(monkeypatch, hour + timedelta(seconds=45))

    await _heartbeat(client, enrolled["token"])
    assert await _hours(db_session, enrolled["machine_id"]) == [
        (hour - timedelta(hours=1), 20),
        (hour, 45),
    ]


async def test_merge_folds_the_source_hours_into_the_target(client, db_session):
    from app.features.usage.models import MachineUptime

    headers = await _admin_headers(client, db_session)
    kept = await _enroll(client, "usage-merge-kept")
    dup = await _enroll(client, "usage-merge-dup")
    shared = NOW.replace(minute=0)
    only_dup = shared - timedelta(hours=1)
    kept_id, dup_id = uuid.UUID(kept["machine_id"]), uuid.UUID(dup["machine_id"])
    db_session.add_all(
        [
            MachineUptime(machine_id=kept_id, hour=shared, seconds_on=1200),
            MachineUptime(machine_id=dup_id, hour=shared, seconds_on=900),
            MachineUptime(machine_id=dup_id, hour=only_dup, seconds_on=3000),
            # An overlap past a full hour is capped, not a failed merge.
            MachineUptime(
                machine_id=kept_id, hour=shared + timedelta(hours=1), seconds_on=3000
            ),
            MachineUptime(
                machine_id=dup_id, hour=shared + timedelta(hours=1), seconds_on=3000
            ),
        ]
    )
    await db_session.commit()

    merged = await client.post(
        f"/api/v1/machines/{kept['machine_id']}/merge",
        headers=headers,
        json={"source_id": dup["machine_id"]},
    )
    assert merged.status_code == 200, merged.text

    assert await _hours(db_session, kept["machine_id"]) == [
        (only_dup, 3000),
        (shared, 2100),
        (shared + timedelta(hours=1), 3600),
    ]
    assert await _hours(db_session, dup["machine_id"]) == []


async def test_counters_go_with_the_machine(client, db_session):
    from app.features.machine.models import Machine
    from app.features.usage.models import MachineUptime

    enrolled = await _enroll(client, "usage-cascade")
    machine_id = uuid.UUID(enrolled["machine_id"])
    db_session.add(
        MachineUptime(machine_id=machine_id, hour=NOW.replace(minute=0), seconds_on=60)
    )
    await db_session.commit()

    await db_session.delete(await db_session.get(Machine, machine_id))
    await db_session.commit()
    assert await _hours(db_session, enrolled["machine_id"]) == []


async def test_usage_policy_reads_the_console_first_then_the_environment(
    db_session,
):
    from app.core.config import settings
    from app.features.setting import crud

    policy = await crud.usage_policy(db_session)
    assert policy == crud.UsagePolicy(
        window_days=settings.USAGE_WINDOW_DAYS,
        low_hours=settings.USAGE_LOW_HOURS,
        high_hours=settings.USAGE_HIGH_HOURS,
    )

    await crud.set_value(db_session, crud.KEY_USAGE_LOW, 4, actor="t@test.local")
    await crud.set_value(db_session, crud.KEY_USAGE_HIGH, 50, actor="t@test.local")
    # A stored boolean is not a number of days, whatever Python thinks.
    await crud.set_value(db_session, crud.KEY_USAGE_WINDOW, True, actor="t@test.local")
    await db_session.commit()

    policy = await crud.usage_policy(db_session)
    assert (policy.low_hours, policy.high_hours) == (4, 50)
    assert policy.window_days == settings.USAGE_WINDOW_DAYS
