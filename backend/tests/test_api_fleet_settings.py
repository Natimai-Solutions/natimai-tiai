"""Parc thresholds and the mail schedule, set from the page Paramètres.

Each one has an initial value in the environment and is then the console's to
change, without a restart: these tests check the precedence, the bounds, and
that every reader — the list, the dashboard, the digest, command queueing,
the agent version reference — follows the stored value.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

from datetime import UTC, datetime, timedelta

STRONG = "correct-horse-battery"


async def _admin(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email="admin@test.local",
        password=STRONG,
        groups=[BuiltinGroup.ADMIN],
    )
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "admin@test.local", "password": STRONG}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _patch(client, headers, **fields):
    return await client.patch("/api/v1/settings", headers=headers, json=fields)


async def _machine(db_session, **fields):
    from app.features.machine.models import Machine

    machine = Machine(machine_uuid=fields.pop("machine_uuid", "m-1"), **fields)
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)
    return machine


# --- Precedence ----------------------------------------------------------------


async def test_environment_values_until_the_console_writes(client, db_session):
    from app.core.config import settings as env

    headers = await _admin(client, db_session)
    body = (await client.get("/api/v1/settings", headers=headers)).json()

    assert body["signature_max_age_days"] == env.SIGNATURE_MAX_AGE_DAYS
    assert body["inactive_after_days"] == env.INACTIVE_AFTER_DAYS
    assert body["low_disk_free_percent"] == env.LOW_DISK_FREE_PERCENT
    assert body["hardware_aging_years"] == env.HARDWARE_AGING_YEARS
    assert body["agent_expected_version"] is None
    assert body["command_default_ttl_minutes"] == env.COMMAND_DEFAULT_TTL_MINUTES
    assert body["digest_hour_utc"] == env.DIGEST_HOUR_UTC
    assert body["maintenance_reminder_weekday"] == env.MAINTENANCE_REMINDER_WEEKDAY
    assert body["env_inactive_after_days"] == env.INACTIVE_AFTER_DAYS


async def test_stored_value_wins_and_null_hands_it_back(client, db_session):
    from app.core.config import settings as env

    headers = await _admin(client, db_session)
    resp = await _patch(
        client,
        headers,
        inactive_after_days=12,
        low_disk_free_percent=20,
        hardware_aging_years=7,
        command_default_ttl_minutes=240,
        digest_hour_utc=6,
        maintenance_reminder_weekday=4,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["inactive_after_days"] == 12
    assert body["low_disk_free_percent"] == 20
    assert body["hardware_aging_years"] == 7
    assert body["command_default_ttl_minutes"] == 240
    assert body["digest_hour_utc"] == 6
    assert body["maintenance_reminder_weekday"] == 4
    # The environment's value stays visible beside it.
    assert body["env_inactive_after_days"] == env.INACTIVE_AFTER_DAYS

    cleared = (await _patch(client, headers, inactive_after_days=None)).json()
    assert cleared["inactive_after_days"] == env.INACTIVE_AFTER_DAYS
    assert cleared["low_disk_free_percent"] == 20  # untouched


async def test_bounds_are_enforced(client, db_session):
    headers = await _admin(client, db_session)
    for field, value in [
        ("signature_max_age_days", 400),
        ("inactive_after_days", 0),
        ("low_disk_free_percent", 0),
        ("low_disk_free_percent", 100),
        ("hardware_aging_years", 31),
        ("command_default_ttl_minutes", 0),
        ("digest_hour_utc", 24),
        ("maintenance_reminder_weekday", 7),
        ("agent_expected_version", "latest"),
        ("agent_expected_version", "1..2"),
    ]:
        resp = await _patch(client, headers, **{field: value})
        assert resp.status_code == 422, (field, value, resp.text)


async def test_a_refused_patch_writes_nothing(client, db_session):
    headers = await _admin(client, db_session)
    before = (await client.get("/api/v1/settings", headers=headers)).json()
    resp = await _patch(client, headers, inactive_after_days=5, digest_hour_utc=99)
    assert resp.status_code == 422
    after = (await client.get("/api/v1/settings", headers=headers)).json()
    assert after["inactive_after_days"] == before["inactive_after_days"]


async def test_readonly_cannot_change_the_thresholds(client, db_session):
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email="ro@test.local",
        password=STRONG,
        groups=[BuiltinGroup.READONLY],
    )
    token = (
        await client.post(
            "/api/v1/auth/login", data={"username": "ro@test.local", "password": STRONG}
        )
    ).json()["access_token"]
    resp = await _patch(
        client, {"Authorization": f"Bearer {token}"}, inactive_after_days=5
    )
    assert resp.status_code == 403


async def test_changes_are_audited(client, db_session):
    headers = await _admin(client, db_session)
    await _patch(client, headers, digest_hour_utc=7)
    entries = (
        await client.get(
            "/api/v1/audit", headers=headers, params={"action": "settings.update"}
        )
    ).json()["items"]
    assert entries[0]["details"]["digest_hour_utc"] == "7"


# --- Every reader follows the stored value --------------------------------------


async def test_signature_threshold_is_applied_to_the_whole_parc_at_once(
    client, db_session
):
    """A poste that is off would otherwise keep the old verdict for ever."""
    from sqlmodel import select

    from app.features.machine.models import Machine

    headers = await _admin(client, db_session)
    # Last reported five days ago with five-day-old signatures, then switched off.
    machine = await _machine(
        db_session,
        av_enabled=True,
        rtp_enabled=True,
        signature_age_days=5,
        is_up_to_date=False,
        last_seen=datetime.now(UTC) - timedelta(days=5),
    )
    machine_id = machine.id

    assert (await _patch(client, headers, signature_max_age_days=7)).status_code == 200
    db_session.expire_all()
    stored = (
        await db_session.exec(
            select(Machine.is_up_to_date).where(Machine.id == machine_id)
        )
    ).one()
    assert stored is True

    listed = (
        await client.get(
            "/api/v1/machines", headers=headers, params={"status": "up_to_date"}
        )
    ).json()
    assert [m["id"] for m in listed["items"]] == [str(machine_id)]

    # And back: tightening the threshold flags it again.
    assert (await _patch(client, headers, signature_max_age_days=2)).status_code == 200
    db_session.expire_all()
    stored = (
        await db_session.exec(
            select(Machine.is_up_to_date).where(Machine.id == machine_id)
        )
    ).one()
    assert stored is False


async def test_heartbeat_uses_the_stored_signature_threshold(client, db_session):
    from sqlmodel import select

    from app.core.config import settings as env
    from app.features.machine.models import Machine

    headers = await _admin(client, db_session)
    assert (await _patch(client, headers, signature_max_age_days=10)).status_code == 200
    enroll = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": env.ENROLLMENT_SECRET},
        json={"machine_uuid": "hb-sig"},
    )
    token = enroll.json()["token"]
    hb = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "defender": {
                "av_enabled": True,
                "rtp_enabled": True,
                "signature_age_days": env.SIGNATURE_MAX_AGE_DAYS + 3,
            }
        },
    )
    assert hb.status_code == 200, hb.text
    stored = (
        await db_session.exec(
            select(Machine.is_up_to_date).where(Machine.machine_uuid == "hb-sig")
        )
    ).one()
    assert stored is True


async def test_inactivity_threshold_reaches_list_dashboard_digest_and_commands(
    client, db_session
):
    from app.features.notification.digest import build_digest, render_digest

    headers = await _admin(client, db_session)
    await _machine(
        db_session,
        hostname="PC-SILENT",
        last_seen=datetime.now(UTC) - timedelta(days=10),
    )

    async def inactive_in_list() -> int:
        resp = await client.get(
            "/api/v1/machines", headers=headers, params={"status": "inactive"}
        )
        return resp.json()["total"]

    async def inactive_on_dashboard() -> int:
        resp = await client.get("/api/v1/stats/overview", headers=headers)
        return resp.json()["inactive"]

    assert await inactive_in_list() == 0
    assert await inactive_on_dashboard() == 0

    assert (await _patch(client, headers, inactive_after_days=5)).status_code == 200
    assert await inactive_in_list() == 1
    assert await inactive_on_dashboard() == 1

    digest = await build_digest(db_session)
    assert digest.inactive == 1
    _subject, text = render_digest(digest)
    assert "Sans contact depuis plus de 5 j : 1 poste(s)" in text

    queued = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "target_status": "inactive"},
    )
    assert queued.status_code == 200, queued.text
    assert queued.json()["count"] == 1


async def test_dashboard_reports_the_stored_disk_and_age_thresholds(client, db_session):
    headers = await _admin(client, db_session)
    await _patch(client, headers, low_disk_free_percent=25, hardware_aging_years=3)
    body = (await client.get("/api/v1/stats/overview", headers=headers)).json()
    assert body["low_disk_free_percent"] == 25
    assert body["hardware_aging_years"] == 3


async def test_command_default_ttl_follows_the_stored_value(client, db_session):
    headers = await _admin(client, db_session)
    machine = await _machine(db_session)
    await _patch(client, headers, command_default_ttl_minutes=15)

    before = datetime.now(UTC)
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "machine_ids": [str(machine.id)]},
    )
    assert resp.status_code == 200, resp.text
    listed = (
        await client.get(
            "/api/v1/commands", headers=headers, params={"machine_id": str(machine.id)}
        )
    ).json()["items"]
    expires = datetime.fromisoformat(listed[0]["expires_at"])
    assert timedelta(minutes=14) < expires - before < timedelta(minutes=16)


async def test_pinned_agent_version_and_explicit_automatic(
    client, db_session, monkeypatch
):
    from app.core.config import settings as env

    headers = await _admin(client, db_session)
    await _machine(db_session, machine_uuid="a", agent_version="1.0.0")
    await _machine(db_session, machine_uuid="b", agent_version="1.1.0")

    async def outdated() -> int:
        resp = await client.get("/api/v1/stats/overview", headers=headers)
        return resp.json()["machines_agent_outdated"]

    # Automatic: the highest reported (1.1.0) is the reference.
    assert await outdated() == 1

    # Pinned from the console to a version nobody runs yet: both are behind.
    assert (
        await _patch(client, headers, agent_expected_version="1.2.0")
    ).status_code == 200
    assert await outdated() == 2

    # A version pinned in the environment, then « automatique » chosen in the
    # console: the console's explicit choice wins.
    monkeypatch.setattr(env, "AGENT_EXPECTED_VERSION", "1.2.0")
    body = (await _patch(client, headers, agent_expected_version="")).json()
    assert body["agent_expected_version"] is None
    assert body["env_agent_expected_version"] == "1.2.0"
    assert await outdated() == 1

    # Cleared: back to the environment's pin.
    await _patch(client, headers, agent_expected_version=None)
    assert await outdated() == 2
