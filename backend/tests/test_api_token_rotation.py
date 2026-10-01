"""Agent token rotation (DB-backed tests require TIAI_TEST_DATABASE_URL).

The property every test here protects: the server never stops honouring a
token the agent may still hold. An offer can be lost, a write can fail on the
poste, an agent can be too old to know about any of it — none of those may
cost the poste its connection.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

# --- Pure rules ----------------------------------------------------------------


def _machine(**fields):
    from app.features.machine.models import Machine

    return Machine(machine_uuid="unit", **fields)


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_a_young_token_is_not_due():
    from app.features.machine.token_rotation import rotation_due

    machine = _machine(token_issued_at=NOW - timedelta(days=29, hours=23))
    assert rotation_due(machine, NOW, 30) is False


def test_a_token_is_due_from_its_age_on():
    from app.features.machine.token_rotation import rotation_due

    machine = _machine(token_issued_at=NOW - timedelta(days=30))
    assert rotation_due(machine, NOW, 30) is True


def test_a_pending_offer_is_always_re_offered():
    """The agent calling with the current token while an offer is pending is
    the sign the offer never reached it — the age no longer matters."""
    from app.features.machine.token_rotation import rotation_due

    machine = _machine(token_issued_at=NOW, pending_token_hash="x")
    assert rotation_due(machine, NOW, 30) is True


def test_zero_days_turns_rotation_off_even_with_an_offer_pending():
    from app.features.machine.token_rotation import rotation_due

    old = _machine(token_issued_at=NOW - timedelta(days=3650))
    pending = _machine(token_issued_at=NOW, pending_token_hash="x")
    assert rotation_due(old, NOW, 0) is False
    assert rotation_due(pending, NOW, 0) is False


def test_an_offer_replaces_the_previous_one():
    from app.core import security
    from app.features.machine.token_rotation import offer_new_token

    machine = _machine(pending_token_hash="stale")
    token = offer_new_token(machine)
    assert machine.pending_token_hash == security.hash_token(token)


def test_promotion_retires_the_current_token_and_restarts_the_clock():
    from app.features.machine.token_rotation import promote_pending

    machine = _machine(
        token_hash="old",
        pending_token_hash="new",
        token_issued_at=NOW - timedelta(days=40),
    )
    promote_pending(machine, NOW)
    assert (machine.token_hash, machine.pending_token_hash) == ("new", None)
    assert machine.token_issued_at == NOW


# --- Through the API ---------------------------------------------------------------


async def _enroll(client, machine_uuid: str) -> dict:
    from app.core.config import settings

    resp = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _heartbeat(client, token: str, *, rotation: bool = True):
    body = {"supports_token_rotation": True} if rotation else {}
    return await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


async def _age_token(db_session, machine_id: str, days: int) -> None:
    """Backdate the current token, as if it had been issued ``days`` ago."""
    from sqlalchemy import update

    from app.features.base import utcnow
    from app.features.machine.models import Machine

    await db_session.exec(
        update(Machine)
        .where(Machine.id == uuid.UUID(machine_id))
        .values(token_issued_at=utcnow() - timedelta(days=days))
    )
    await db_session.commit()


async def _row(db_session, machine_id: str):
    from sqlmodel import select

    from app.features.machine.models import Machine

    db_session.expire_all()
    result = await db_session.exec(
        select(Machine).where(Machine.id == uuid.UUID(machine_id))
    )
    return result.one()


async def _admin_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email="rotation-admin@test.local",
        password="pw",
        groups=[BuiltinGroup.ADMIN],
    )
    await db_session.commit()
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "rotation-admin@test.local", "password": "pw"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_a_fresh_token_is_not_renewed(client, db_session):
    enrolled = await _enroll(client, "rot-fresh")

    resp = await _heartbeat(client, enrolled["token"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["new_token"] is None
    assert (await _row(db_session, enrolled["machine_id"])).pending_token_hash is None


async def test_enrollment_starts_the_clock(client, db_session):
    from app.features.base import utcnow

    before = utcnow()
    enrolled = await _enroll(client, "rot-clock")
    row = await _row(db_session, enrolled["machine_id"])
    assert row.token_issued_at >= before


async def test_full_cycle_offer_promotion_and_old_token_refused(client, db_session):
    """The nominal path, end to end."""
    enrolled = await _enroll(client, "rot-cycle")
    old_token = enrolled["token"]
    await _age_token(db_session, enrolled["machine_id"], 31)

    # Offered on the heartbeat authenticated by the aged token.
    resp = await _heartbeat(client, old_token)
    assert resp.status_code == 200, resp.text
    new_token = resp.json()["new_token"]
    assert new_token and new_token != old_token

    # Held as pending, next to the current one: nothing is retired before the
    # agent proves it has the new token (the lost-response test covers the
    # old one still working in between).
    from app.core import security

    row = await _row(db_session, enrolled["machine_id"])
    assert row.pending_token_hash == security.hash_token(new_token)
    assert row.token_hash == security.hash_token(old_token)

    # First use of the new token promotes it...
    resp = await _heartbeat(client, new_token)
    assert resp.status_code == 200, resp.text
    # ...restarts the clock, so nothing more is offered...
    assert resp.json()["new_token"] is None
    row = await _row(db_session, enrolled["machine_id"])
    assert row.token_hash == security.hash_token(new_token)
    assert row.pending_token_hash is None
    assert datetime.now(UTC) - row.token_issued_at < timedelta(minutes=1)

    # ...and the old one is dead.
    resp = await _heartbeat(client, old_token)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth.token.invalid"


async def test_a_lost_offer_is_replaced_and_the_lost_token_dies(client, db_session):
    """The response carrying the token never reached the agent.

    The agent carries on with its current token, which must keep working; the
    server offers a new token in place of the lost one, which must not stay
    valid — nobody is known to hold it, and somebody might.
    """
    enrolled = await _enroll(client, "rot-lost")
    old_token = enrolled["token"]
    await _age_token(db_session, enrolled["machine_id"], 31)

    lost = (await _heartbeat(client, old_token)).json()["new_token"]
    assert lost

    resp = await _heartbeat(client, old_token)
    assert resp.status_code == 200, resp.text
    second = resp.json()["new_token"]
    assert second and second != lost

    assert (await _heartbeat(client, lost)).status_code == 401
    resp = await _heartbeat(client, second)
    assert resp.status_code == 200
    assert resp.json()["new_token"] is None
    assert (await _heartbeat(client, old_token)).status_code == 401


async def test_promotion_happens_on_any_agent_endpoint(client, db_session):
    """The agent's first request with the new token may be a command result,
    one the server ignores at that — it promotes all the same."""
    enrolled = await _enroll(client, "rot-result")
    old_token = enrolled["token"]
    await _age_token(db_session, enrolled["machine_id"], 31)
    new_token = (await _heartbeat(client, old_token)).json()["new_token"]

    resp = await client.post(
        f"/api/v1/agent/commands/{uuid.uuid4()}/result",
        headers={"Authorization": f"Bearer {new_token}"},
        json={"status": "succeeded"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}

    assert (await _heartbeat(client, old_token)).status_code == 401
    assert (await _heartbeat(client, new_token)).status_code == 200


async def test_an_agent_without_the_capability_is_never_offered_a_token(
    client, db_session
):
    """An older agent could not store the token: it is left entirely alone."""
    enrolled = await _enroll(client, "rot-legacy")
    token = enrolled["token"]
    await _age_token(db_session, enrolled["machine_id"], 400)
    issued = (await _row(db_session, enrolled["machine_id"])).token_issued_at

    for _ in range(3):
        resp = await _heartbeat(client, token, rotation=False)
        assert resp.status_code == 200, resp.text
        assert resp.json()["new_token"] is None

    row = await _row(db_session, enrolled["machine_id"])
    assert row.pending_token_hash is None
    assert row.token_issued_at == issued


async def test_zero_days_disables_rotation(client, db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "AGENT_TOKEN_ROTATE_DAYS", 0)
    enrolled = await _enroll(client, "rot-off")
    await _age_token(db_session, enrolled["machine_id"], 4000)

    resp = await _heartbeat(client, enrolled["token"])
    assert resp.status_code == 200
    assert resp.json()["new_token"] is None


async def test_the_age_is_configurable(client, db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "AGENT_TOKEN_ROTATE_DAYS", 7)
    enrolled = await _enroll(client, "rot-seven")
    await _age_token(db_session, enrolled["machine_id"], 8)

    assert (await _heartbeat(client, enrolled["token"])).json()["new_token"]


async def test_revocation_also_kills_a_pending_token(client, db_session):
    """A revocation that left the offered token valid would leave the poste
    one request away from working again — through the very kill-switch."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "rot-revoke")
    machine_id = enrolled["machine_id"]
    await _age_token(db_session, machine_id, 31)
    pending = (await _heartbeat(client, enrolled["token"])).json()["new_token"]
    assert pending

    resp = await client.post(
        f"/api/v1/machines/{machine_id}/revoke-token", headers=headers
    )
    assert resp.status_code == 200
    assert (await _row(db_session, machine_id)).pending_token_hash is None

    # Refused while revoked, and not promoted by the attempt.
    resp = await _heartbeat(client, pending)
    assert resp.status_code == 401

    # Lifting the revocation does not bring it back either.
    resp = await client.post(
        f"/api/v1/machines/{machine_id}/allow-reenroll", headers=headers
    )
    assert resp.status_code == 200
    assert (await _heartbeat(client, pending)).status_code == 401
    assert (await _heartbeat(client, enrolled["token"])).status_code == 401


async def test_a_revoked_machine_cannot_promote_its_pending_token(client, db_session):
    """Revocation checked before promotion: the pending hash, had it somehow
    survived, must not become the current token of a revoked poste."""
    from sqlalchemy import update

    from app.core import security
    from app.features.machine.models import Machine

    enrolled = await _enroll(client, "rot-revoked-promote")
    machine_id = enrolled["machine_id"]
    await _age_token(db_session, machine_id, 31)
    pending = (await _heartbeat(client, enrolled["token"])).json()["new_token"]
    await db_session.exec(
        update(Machine)
        .where(Machine.id == uuid.UUID(machine_id))
        .values(token_revoked=True)
    )
    await db_session.commit()

    resp = await _heartbeat(client, pending)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth.token.revoked"
    row = await _row(db_session, machine_id)
    assert row.token_hash == security.hash_token(enrolled["token"])
    assert row.pending_token_hash == security.hash_token(pending)


async def test_re_enrollment_drops_a_pending_token(client, db_session):
    enrolled = await _enroll(client, "rot-reenroll")
    await _age_token(db_session, enrolled["machine_id"], 31)
    pending = (await _heartbeat(client, enrolled["token"])).json()["new_token"]

    again = await _enroll(client, "rot-reenroll")
    assert again["machine_id"] == enrolled["machine_id"]

    row = await _row(db_session, enrolled["machine_id"])
    assert row.pending_token_hash is None
    assert datetime.now(UTC) - row.token_issued_at < timedelta(minutes=1)
    assert (await _heartbeat(client, pending)).status_code == 401
    resp = await _heartbeat(client, again["token"])
    assert resp.status_code == 200
    assert resp.json()["new_token"] is None


@pytest.mark.parametrize("days", [-1, 3651])
def test_the_setting_is_bounded(days, monkeypatch):
    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv("AGENT_TOKEN_ROTATE_DAYS", str(days))
    with pytest.raises(ValidationError, match="AGENT_TOKEN_ROTATE_DAYS"):
        Settings(_env_file=None)
