"""The software catalogue budget: what is charged, the fleet-wide bound, and
a list cut short that is said so and asked for again.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid

import pytest

STRONG = "correct-horse-battery"


async def _admin(client, db_session):
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


async def _enroll(client, machine_uuid):
    from app.core.config import settings

    resp = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid, "hostname": machine_uuid.upper()},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _heartbeat(client, enrolled, **body) -> dict:
    resp = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {enrolled['token']}"},
        json=body,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _inventory(names, hash_="h1", **extra) -> dict:
    return {
        "inventory": {
            "hash": hash_,
            "software": [{"name": n, "version": "1"} for n in names],
            **extra,
        }
    }


async def _catalogue(db_session) -> int:
    from sqlmodel import func, select

    from app.features.inventory.models import Software

    return await db_session.scalar(select(func.count()).select_from(Software))


async def _detail(client, headers, enrolled) -> dict:
    resp = await client.get(
        f"/api/v1/machines/{enrolled['machine_id']}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def budgets(monkeypatch):
    """Small budgets: (per poste, fleet)."""
    from app.features.inventory import budget

    def set_budgets(poste: int, fleet: int) -> None:
        monkeypatch.setattr(budget.software_quota, "units", poste)
        monkeypatch.setattr(budget.software_fleet_quota, "units", fleet)

    return set_budgets


async def _poste_left(db_session, enrolled) -> int:
    from app.features.inventory import budget

    return await budget.poste_budget_left(db_session, enrolled["machine_id"])


async def _fleet_left(db_session) -> int:
    from app.features.inventory import budget

    return await budget.fleet_budget_left(db_session)


async def _forget(db_session, quota) -> None:
    """Empty a budget's window: what a day going by does."""
    from sqlalchemy import delete
    from sqlmodel import col

    from app.features.counter.models import SharedCounter

    await db_session.exec(
        delete(SharedCounter).where(col(SharedCounter.name) == quota.name)
    )
    await db_session.commit()


# --- What is charged ----------------------------------------------------------


@pytest.mark.parametrize("with_savepoint", [False, True])
async def test_a_heartbeat_that_fails_does_not_spend_the_budget(
    client, db_session, budgets, monkeypatch, with_savepoint
):
    """The catalogue rows of a heartbeat that fails further down are rolled
    back: the budget they were granted from comes back with them. Also when
    a savepoint was released on the way (the directory placement), which is
    a commit of its own for the session's events and not the one that counts."""
    from app.core.config import settings
    from app.features.usage import crud as usage_crud

    budgets(3, 100)
    a = await _enroll(client, "pc-a")
    extra = {}
    if with_savepoint:
        monkeypatch.setattr(settings, "ROOM_SOURCE", "ad_ou")
        extra["directory"] = {
            "distinguished_name": "CN=PC,OU=B12,DC=lycee,DC=local",
            "ou": "B12",
            "ou_dn": "OU=B12,DC=lycee,DC=local",
        }

    real = usage_crud.record

    async def broken(*_args, **_kwargs):
        raise RuntimeError("the heartbeat fails after the inventory")

    monkeypatch.setattr(usage_crud, "record", broken)
    with pytest.raises(RuntimeError):
        await _heartbeat(client, a, **_inventory(["s1", "s2", "s3"], **extra))
    assert await _catalogue(db_session) == 0
    assert await _poste_left(db_session, a) == 3
    assert await _fleet_left(db_session) == 100

    # The same list sent again is applied whole: nothing was paid for the
    # rows that never existed.
    monkeypatch.setattr(usage_crud, "record", real)
    body = await _heartbeat(client, a, **_inventory(["s1", "s2", "s3"], **extra))
    assert body["resend_inventory"] is False
    assert await _catalogue(db_session) == 3
    assert await _poste_left(db_session, a) == 0
    assert await _fleet_left(db_session) == 97


async def test_a_committed_heartbeat_spends_exactly_what_it_created(
    client, db_session, budgets
):

    budgets(10, 100)
    a = await _enroll(client, "pc-a")
    await _heartbeat(client, a, **_inventory(["s1", "s2", "s3"]))
    assert await _poste_left(db_session, a) == 7
    # Known entries are free.
    await _heartbeat(client, a, **_inventory(["s1", "s2", "s3", "s4"], "h2"))
    assert await _poste_left(db_session, a) == 6
    assert await _fleet_left(db_session) == 96


# --- The fleet-wide budget ----------------------------------------------------


async def test_many_postes_together_are_bounded_by_the_fleet_budget(
    client, db_session, budgets
):
    """Each forged poste has a budget of its own; together they create no
    more than the fleet's, and a poste is granted the smaller of the two."""
    budgets(3, 5)
    postes = [await _enroll(client, f"pc-{n}") for n in range(4)]
    counts = []
    for n, poste in enumerate(postes):
        await _heartbeat(
            client, poste, **_inventory([f"p{n}-{i}" for i in range(10)], f"h{n}")
        )
        counts.append(await _catalogue(db_session))
    # 3 (its own budget), then 2 (what the fleet has left), then nothing.
    assert counts == [3, 5, 5, 5]


def test_the_fleet_budget_is_the_setting():
    from app.core.config import settings
    from app.features.inventory import budget

    assert settings.SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET == 50_000
    assert budget.software_fleet_quota.units == (
        settings.SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET
    )
    assert budget.software_fleet_quota.window_seconds == 24 * 3600


# --- A list cut short ---------------------------------------------------------


async def _cut_long_ago(db_session, enrolled) -> None:
    """Date the cut of the poste's software list back past the delay the
    server waits before asking for it again."""
    from datetime import timedelta

    from app.api.routes.agent import RESEND_INVENTORY_AFTER
    from app.features.base import utcnow
    from app.features.machine.models import Machine

    machine = await db_session.get(Machine, uuid.UUID(enrolled["machine_id"]))
    await db_session.refresh(machine)
    machine.software_truncated_at = (
        utcnow() - RESEND_INVENTORY_AFTER - timedelta(minutes=1)
    )
    db_session.add(machine)
    await db_session.commit()


async def test_a_truncated_list_is_flagged_then_asked_again_and_completed(
    client, db_session, budgets
):
    from app.features.inventory import budget
    from app.features.machine.models import Machine

    budgets(3, 100)
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a")
    names = ["s1", "s2", "s3", "s4", "s5"]

    assert (await _detail(client, headers, a))["software_truncated"] is False

    # Cut short: said in the fiche, and no resend asked while the budget is
    # empty — it would be cut again.
    body = await _heartbeat(client, a, **_inventory(names))
    assert body["resend_inventory"] is False
    detail = await _detail(client, headers, a)
    assert detail["software_truncated"] is True
    assert len(detail["software"]) == 3
    assert (await _heartbeat(client, a))["resend_inventory"] is False
    machine = await db_session.get(Machine, uuid.UUID(a["machine_id"]))
    assert machine.software_truncated_at is not None

    # The budget is back, but the cut is minutes old: not asked yet — a
    # budget being drained must not have every poste re-upload at each tick.
    await _forget(db_session, budget.software_quota)
    assert (await _heartbeat(client, a))["resend_inventory"] is False

    # An hour after the cut, the next heartbeat asks for the list.
    await _cut_long_ago(db_session, a)
    assert (await _heartbeat(client, a))["resend_inventory"] is True

    # The agent sends it again: applied whole, the flag is cleared and
    # nothing more is asked.
    body = await _heartbeat(client, a, **_inventory(names))
    assert body["resend_inventory"] is False
    detail = await _detail(client, headers, a)
    assert detail["software_truncated"] is False
    assert sorted(s["name"] for s in detail["software"]) == names
    assert (await _heartbeat(client, a))["resend_inventory"] is False
    await db_session.refresh(machine)
    assert machine.software_truncated_at is None
    assert machine.inventory_hash == "h1"


async def test_no_resend_is_asked_while_the_fleet_budget_is_empty(
    client, db_session, budgets
):
    """Both budgets must have room: the poste's own being back is not enough
    while the fleet's is spent."""
    from app.features.inventory import budget

    budgets(3, 3)
    a = await _enroll(client, "pc-a")
    await _heartbeat(client, a, **_inventory(["s1", "s2", "s3", "s4"]))
    await _forget(db_session, budget.software_quota)
    assert await _poste_left(db_session, a) == 3
    assert (await _heartbeat(client, a))["resend_inventory"] is False

    await _forget(db_session, budget.software_fleet_quota)
    await _cut_long_ago(db_session, a)
    assert (await _heartbeat(client, a))["resend_inventory"] is True


async def test_an_inventory_without_a_software_block_leaves_the_flag_alone(
    client, db_session, budgets
):
    budgets(1, 100)
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a")
    await _heartbeat(client, a, **_inventory(["s1", "s2"]))
    await _heartbeat(client, a, inventory={"hash": "hw-only", "cpu_cores": 4})
    assert (await _detail(client, headers, a))["software_truncated"] is True
