"""Two-person approval of mass actions (C10): the schedules — approved once,
when written, for an author and a number of postes; asked again when
rewritten, turned back on by someone else or grown; the guard at the start
of a run; the rings (require TIAI_TEST_DATABASE_URL)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import col, select

from app.core.config import settings
from app.features.user.permissions import BuiltinGroup
from tests.scope_helpers import account, machine
from tests.test_approvals import API, _audit, _enable, _outbox, _package
from tests.test_schedules import (
    _commands,
    _create,
    _finish,
    _once,
    _run,
    _runs,
    _schedule,
    _two_rooms,
)

NOW = datetime.now(UTC).replace(second=0, microsecond=0)


@pytest.fixture
def mail(monkeypatch):
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key")
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.test")


async def _setup(client, db_session, postes=3, threshold=2):
    await _enable(db_session, threshold=threshold)
    author = await account(
        client, db_session, "auteur@test.local", [BuiltinGroup.ADMIN]
    )
    other = await account(client, db_session, "second@test.local", [BuiltinGroup.ADMIN])
    for i in range(postes):
        await machine(db_session, f"PC-{i}")
    return author, other


def _reboot(at, **fields):
    return _once(at, **{"name": "Redémarrage", "command_type": "reboot", **fields})


def _weekly(**fields):
    return {
        "name": "Redémarrage du mercredi",
        "command_type": "reboot",
        "target": {"kind": "all"},
        "recurrence": "weekly",
        "weekdays": [2],
        "time_of_day": "20:00",
        **fields,
    }


async def _requests(db_session, schedule_id):
    from app.features.approval.models import ApprovalRequest

    db_session.expire_all()
    return list(
        (
            await db_session.exec(
                select(ApprovalRequest)
                .where(col(ApprovalRequest.schedule_id) == uuid.UUID(schedule_id))
                .order_by(col(ApprovalRequest.requested_at))
            )
        ).all()
    )


async def _decide(client, headers, approval_id, action="approve", status=200, **body):
    resp = await client.post(
        f"{API}/{approval_id}/{action}", headers=headers, json=body
    )
    assert resp.status_code == status, resp.text
    return resp.json()


async def _user_id(db_session, email):
    from app.features.user import crud as user_crud

    db_session.expire_all()
    return (await user_crud.get_by_email(db_session, email)).id


# --- Written, approved, run --------------------------------------------------------


async def test_a_schedule_at_risk_waits_for_its_approval(client, db_session):
    author, other = await _setup(client, db_session)
    at = NOW + timedelta(hours=2)
    created = await _create(client, author, _reboot(at))
    assert created["state"] == "to_approve" and created["next_run_at"] is None
    assert created["approval"]["status"] == "pending"
    [entry] = await _audit(db_session, "schedule.create")
    assert entry.details["approval"] == "required"
    assert await _run(db_session, at) == 0

    # Its author cannot approve it.
    resp = await client.post(
        f"{API}/{created['approval']['id']}/approve", headers=author, json={}
    )
    assert resp.status_code == 403
    await _decide(client, other, created["approval"]["id"])
    schedule = await _schedule(db_session, created["id"])
    assert schedule.state == "active" and schedule.next_run_at == at
    assert schedule.approved_by == "second@test.local"
    assert schedule.approved_for_id == await _user_id(db_session, "auteur@test.local")
    assert (await _schedule(db_session, created["id"])).approved_count == 3
    out = (
        await client.get(f"/api/v1/schedules/{created['id']}", headers=author)
    ).json()
    assert out["approval"]["approved_by"] == "second@test.local"
    assert out["approval"]["approved_count"] == 3
    assert await _run(db_session, at) == 1
    assert len(await _commands(db_session, type="reboot")) == 3


async def test_under_the_threshold_or_turned_off_nothing_waits(client, db_session):
    author, _ = await _setup(client, db_session, threshold=3)
    at = NOW + timedelta(hours=2)
    assert (await _create(client, author, _reboot(at)))["state"] == "active"
    # An everyday command never waits.
    await machine(db_session, "PC-X")
    created = await _create(client, author, _once(at))
    assert created["state"] == "active" and created["approval"] is None
    await _enable(db_session, threshold=2, enabled=False)
    assert (await _create(client, author, _reboot(at)))["state"] == "active"


async def test_the_rings_count_together_and_run_through(client, db_session):
    from app.features.approval.models import ApprovalRequest

    await _enable(db_session, threshold=3)
    author = await account(
        client, db_session, "auteur@test.local", [BuiltinGroup.ADMIN]
    )
    other = await account(client, db_session, "second@test.local", [BuiltinGroup.ADMIN])
    rooms = await _two_rooms(client, author, db_session)
    at = NOW + timedelta(hours=1)
    # Two stages of two postes: four together, above three.
    created = await _create(client, author, _ringed(at, rooms))
    assert created["state"] == "to_approve"
    [request] = await _requests(db_session, created["id"])
    assert request.machine_count == 4
    await _decide(client, other, str(request.id))
    await _run(db_session, at)
    [run] = await _runs(db_session, created["id"])
    await _finish(db_session, run.id, ["succeeded", "succeeded"])
    await _run(db_session, at + timedelta(hours=2))
    [run] = await _runs(db_session, created["id"])
    assert run.stage == 1 and run.created == 4 and run.status == "done"
    db_session.expire_all()
    assert len((await db_session.exec(select(ApprovalRequest))).all()) == 1


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


# --- Rewritten, turned off and on, deleted -----------------------------------------


async def test_rewriting_asks_again(client, db_session):
    author, other = await _setup(client, db_session)
    payload = _weekly()
    created = await _create(client, author, payload)
    first = created["approval"]["id"]
    resp = await client.put(
        f"/api/v1/schedules/{created['id']}", headers=author, json=payload
    )
    assert resp.status_code == 200 and resp.json()["state"] == "to_approve"
    old, new = await _requests(db_session, created["id"])
    assert str(old.id) == first
    assert old.status == "cancelled" and old.result_code == "schedule_changed"
    assert new.status == "pending"
    new_id = str(new.id)
    [cancel] = await _audit(db_session, "approval.cancel")
    assert cancel.details["cause"] == "schedule_changed"

    await _decide(client, other, new_id)
    assert (await _schedule(db_session, created["id"])).state == "active"
    resp = await client.put(
        f"/api/v1/schedules/{created['id']}",
        headers=author,
        json={**payload, "time_of_day": "21:00"},
    )
    assert resp.json()["state"] == "to_approve"
    schedule = await _schedule(db_session, created["id"])
    assert schedule.approved_at is None and schedule.approved_count is None
    assert len(await _requests(db_session, created["id"])) == 3


@pytest.mark.parametrize("policy_on", [True, False])
async def test_rewriting_during_stage_one_does_not_start_stage_two(
    client, db_session, policy_on
):
    await _enable(db_session, threshold=3)
    author = await account(
        client, db_session, "auteur@test.local", [BuiltinGroup.ADMIN]
    )
    other = await account(client, db_session, "second@test.local", [BuiltinGroup.ADMIN])
    rooms = await _two_rooms(client, author, db_session)
    at = NOW + timedelta(hours=1)
    created = await _create(client, author, _ringed(at, rooms))
    await _decide(client, other, created["approval"]["id"])
    await _run(db_session, at)
    [run] = await _runs(db_session, created["id"])
    await _finish(db_session, run.id, ["succeeded", "succeeded"])
    if not policy_on:
        await _enable(db_session, threshold=3, enabled=False)
    # Rewritten while the pilot is observed: back to « active » with the
    # approval off, « to_approve » with it on.
    resp = await client.put(
        f"/api/v1/schedules/{created['id']}",
        headers=other,
        json=_ringed(at + timedelta(days=2), list(reversed(rooms))),
    )
    assert resp.json()["state"] == ("to_approve" if policy_on else "active")
    await _run(db_session, at + timedelta(hours=3))
    [run] = await _runs(db_session, created["id"])
    assert run.status == "halted" and run.result_code == "schedule_changed"
    stages = {c.schedule_stage for c in await _commands(db_session, type="wu_install")}
    assert stages == {0}


async def test_turned_back_on(client, db_session):
    from app.features.user import crud as user_crud

    author, other = await _setup(client, db_session)
    third = await account(client, db_session, "trois@test.local", [BuiltinGroup.ADMIN])
    created = await _create(client, author, _weekly())
    await _decide(client, other, created["approval"]["id"])
    url = f"/api/v1/schedules/{created['id']}/state"

    async def toggle(headers):
        resp = await client.post(url, headers=headers, json={"enabled": False})
        assert resp.status_code == 200
        resp = await client.post(url, headers=headers, json={"enabled": True})
        assert resp.status_code == 200, resp.text
        return resp.json()

    # By its approved author, unchanged: active, nothing asked.
    assert (await toggle(author))["state"] == "active"
    assert len(await _requests(db_session, created["id"])) == 1
    # By an unrestricted third account: asked again, counted in its scope.
    out = await toggle(third)
    assert out["state"] == "to_approve"
    requests = await _requests(db_session, created["id"])
    assert len(requests) == 2 and requests[-1].requested_by == "trois@test.local"
    assert requests[-1].machine_count == 3
    await _decide(client, other, str(requests[-1].id))
    # By the approver: asked again, which they cannot approve themselves.
    out = await toggle(other)
    assert out["state"] == "to_approve"
    request = (await _requests(db_session, created["id"]))[-1]
    resp = await client.post(f"{API}/{request.id}/approve", headers=other, json={})
    assert (
        resp.status_code == 403
        and resp.json()["error"]["code"] == "approval.own_request"
    )
    # A target grown past what was approved: asked again.
    await _decide(client, third, str(request.id))
    await machine(db_session, "PC-NEW")
    out = await toggle(other)
    assert out["state"] == "to_approve"
    assert await user_crud.get_by_email(db_session, "trois@test.local")


async def test_turned_off_or_deleted_while_waiting(client, db_session):
    from app.features.approval.models import ApprovalRequest

    author, _ = await _setup(client, db_session)
    created = await _create(client, author, _weekly())
    resp = await client.post(
        f"/api/v1/schedules/{created['id']}/state",
        headers=author,
        json={"enabled": False},
    )
    assert resp.json()["state"] == "disabled"
    [request] = await _requests(db_session, created["id"])
    assert request.status == "cancelled" and request.result_code == "schedule_disabled"

    second = await _create(client, author, _weekly(name="Autre"))
    resp = await client.delete(f"/api/v1/schedules/{second['id']}", headers=author)
    assert resp.status_code == 204
    db_session.expire_all()
    assert (
        await db_session.get(ApprovalRequest, uuid.UUID(second["approval"]["id"]))
    ) is None


# --- Rejected, expired, failed -----------------------------------------------------


async def test_rejected_or_expired_it_is_suspended(client, db_session, mail):
    from app.features.approval import crud

    author, other = await _setup(client, db_session)
    rejected = await _create(client, author, _weekly())
    await _decide(client, other, rejected["approval"]["id"], "reject", note="Non")
    schedule = await _schedule(db_session, rejected["id"])
    assert (
        schedule.state == "suspended" and schedule.suspended_code == "approval_rejected"
    )

    expired = await _create(client, author, _weekly(name="Autre"))
    assert await crud.mark_expired(db_session, NOW + timedelta(days=2)) == 1
    schedule = await _schedule(db_session, expired["id"])
    assert (
        schedule.state == "suspended" and schedule.suspended_code == "approval_expired"
    )
    subjects = [m.subject for m in await _outbox(db_session, "auteur@test.local")]
    assert any("refusée" in s for s in subjects) and any(
        "expiré" in s for s in subjects
    )


async def test_a_failed_approval_suspends_it_before_the_answer(client, db_session):
    from app.features.package.models import Package
    from app.features.schedule import windows
    from app.features.setting.crud import set_value
    from app.features.user import crud as user_crud

    author, other = await _setup(client, db_session)
    tech = await account(client, db_session, "tech@test.local", [BuiltinGroup.ADMIN])

    # The author deactivated.
    deactivated = await _create(client, tech, _weekly(name="A"))
    user = await user_crud.get_by_email(db_session, "tech@test.local")
    user.is_active = False
    db_session.add(user)
    await db_session.commit()
    resp = await client.post(
        f"{API}/{deactivated['approval']['id']}/approve", headers=other, json={}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "approval.author_not_allowed"
    schedule = await _schedule(db_session, deactivated["id"])
    assert (schedule.state, schedule.suspended_code) == ("suspended", "author_inactive")
    [request] = await _requests(db_session, deactivated["id"])
    assert request.status == "failed"

    # A one-off whose hour has passed.
    past = await _create(client, author, _reboot(NOW + timedelta(hours=2), name="B"))
    row = await _schedule(db_session, past["id"])
    row.run_at = NOW - timedelta(minutes=5)
    db_session.add(row)
    await db_session.commit()
    resp = await client.post(
        f"{API}/{past['approval']['id']}/approve", headers=other, json={}
    )
    assert (
        resp.status_code == 422 and resp.json()["error"]["code"] == "schedule.in_past"
    )
    assert (await _requests(db_session, past["id"]))[0].result_code == "in_past"

    # A forbidden window added since.
    windowed = await _create(client, author, _weekly(name="C"))
    await set_value(
        db_session,
        windows.KEY_FORBIDDEN,
        [{"days": [2], "start": "19:00", "end": "22:00"}],
        actor="t",
    )
    await db_session.commit()
    resp = await client.post(
        f"{API}/{windowed['approval']['id']}/approve", headers=other, json={}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "schedule.forbidden_window"
    schedule = await _schedule(db_session, windowed["id"])
    assert schedule.suspended_code == "forbidden_window"

    # A package deleted.
    package_id = await _package(db_session)
    deploy = await _create(
        client,
        author,
        _weekly(
            name="D",
            command_type="package_install",
            package_id=str(package_id),
            time_of_day="23:00",
        ),
    )
    await db_session.delete(await db_session.get(Package, package_id))
    await db_session.commit()
    resp = await client.post(
        f"{API}/{deploy['approval']['id']}/approve", headers=other, json={}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "approval.package_gone"
    assert (await _schedule(db_session, deploy["id"])).suspended_code == "package_gone"


# --- The guard at the start of a run ----------------------------------------------


async def test_the_guard_suspends_what_was_never_approved(client, db_session, mail):
    author, _ = await _setup(client, db_session)
    await _enable(db_session, threshold=2, enabled=False)
    at = NOW + timedelta(hours=1)
    created = await _create(client, author, _reboot(at))
    assert created["state"] == "active"
    await _enable(db_session, threshold=2)
    await _run(db_session, at)
    [run] = await _runs(db_session, created["id"])
    assert run.status == "suspended" and run.result_code == "approval_required"
    assert run.result_params == {"count": 3, "threshold": 2}
    schedule = await _schedule(db_session, created["id"])
    assert schedule.suspended_code == "approval_required"
    assert await _commands(db_session, type="reboot") == []
    [told] = await _outbox(db_session, "auteur@test.local")
    assert "seuil d'approbation" in told.body


async def test_the_guard_counts_every_stage_together(client, db_session):
    await _enable(db_session, threshold=3, enabled=False)
    author = await account(
        client, db_session, "auteur@test.local", [BuiltinGroup.ADMIN]
    )
    await account(client, db_session, "second@test.local", [BuiltinGroup.ADMIN])
    rooms = await _two_rooms(client, author, db_session)
    at = NOW + timedelta(hours=1)
    # Two stages of two postes each, under three apiece, four together.
    created = await _create(client, author, _ringed(at, rooms))
    await _enable(db_session, threshold=3)
    await _run(db_session, at)
    [run] = await _runs(db_session, created["id"])
    assert run.status == "suspended" and run.result_code == "approval_required"
    assert await _commands(db_session, type="wu_install") == []


async def test_the_guard_and_what_was_approved(client, db_session):
    author, other = await _setup(client, db_session)
    created = await _create(client, author, _weekly())
    await _decide(client, other, created["approval"]["id"])
    first = (await _schedule(db_session, created["id"])).next_run_at
    # Under what was approved: it runs.
    await _run(db_session, first)
    [run] = await _runs(db_session, created["id"])
    assert run.status == "done" and run.created == 3
    # Grown past it: suspended.
    await machine(db_session, "PC-NEW")
    second = first + timedelta(days=7)
    await _run(db_session, second)
    runs = await _runs(db_session, created["id"])
    assert runs[-1].status == "suspended"
    assert runs[-1].result_params == {"count": 4, "threshold": 2}


async def test_the_guard_does_not_recount_later_stages(client, db_session):
    await _enable(db_session, threshold=3)
    author = await account(
        client, db_session, "auteur@test.local", [BuiltinGroup.ADMIN]
    )
    other = await account(client, db_session, "second@test.local", [BuiltinGroup.ADMIN])
    rooms = await _two_rooms(client, author, db_session)
    at = NOW + timedelta(hours=1)
    created = await _create(client, author, _ringed(at, rooms))
    await _decide(client, other, created["approval"]["id"])
    await _run(db_session, at)
    [run] = await _runs(db_session, created["id"])
    await _finish(db_session, run.id, ["succeeded", "succeeded"])
    # The second room grows past what was approved meanwhile.
    for n in range(2):
        await machine(db_session, f"NEW-{n}", room_id=uuid.UUID(rooms[1]))
    await _run(db_session, at + timedelta(hours=2))
    [run] = await _runs(db_session, created["id"])
    assert run.stage == 1 and run.created == 6


# --- The console's zone -------------------------------------------------------------


async def test_a_zone_change_and_schedules_waiting(client, db_session):
    author, _ = await _setup(client, db_session)
    at = NOW + timedelta(days=3)
    once = await _create(client, author, _reboot(at))
    weekly = await _create(client, author, _weekly(name="Hebdo"))
    before = (await _schedule(db_session, once["id"])).run_at
    resp = await client.patch(
        "/api/v1/settings", headers=author, json={"console_timezone": "Europe/Paris"}
    )
    assert resp.status_code == 200, resp.text
    one_off = await _schedule(db_session, once["id"])
    assert one_off.run_at != before and one_off.next_run_at is None
    assert one_off.state == "to_approve"
    assert (await _schedule(db_session, weekly["id"])).next_run_at is None


# --- The mail's causes ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("fr", "au-delà du seuil d'approbation (40)"),
        ("en", "above the approval threshold (40)"),
    ],
)
def test_the_stop_mail_says_why(language, expected):
    from app.features.notification import schedule_mail
    from app.features.user.models import Language

    _, body = schedule_mail.render(
        name="X",
        code="approval_required",
        params={"count": 45, "threshold": 40},
        language=Language(language),
    )
    assert expected in body
    for code in ("approval_rejected", "approval_expired"):
        _, body = schedule_mail.render(
            name="X", code=code, params={}, language=Language(language)
        )
        assert code not in body
