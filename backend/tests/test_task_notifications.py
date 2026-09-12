"""Mail about somebody's tasks: the assignment of a verification, the
personal block of the digest, the weekly maintenance reminder — all behind
the account's e-mail setting.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings

STRONG = "correct-horse-battery"


@pytest.fixture
def mailgun_configured(monkeypatch):
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.test.local")
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-test")
    monkeypatch.setattr(settings, "CONSOLE_BASE_URL", "https://tiai.test")


async def _queued(db_session):
    from sqlmodel import col, select

    from app.features.notification.models import EmailOutbox

    rows = await db_session.exec(
        select(EmailOutbox).order_by(col(EmailOutbox.created_at))
    )
    return list(rows.all())


async def _user(
    client, db_session, email, groups, preference="digest_daily", name=None
):
    from app.features.user import crud

    user = await crud.create_user(
        db_session, email=email, password=STRONG, groups=groups, full_name=name
    )
    user_id = str(user.id)
    user.email_preference = preference
    db_session.add(user)
    await db_session.commit()
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": STRONG}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user_id


async def _admin(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    return await _user(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])


async def _tech(client, db_session, preference="digest_daily"):
    from app.features.user.permissions import BuiltinGroup

    return await _user(
        client,
        db_session,
        "tech@test.local",
        [BuiltinGroup.TECHNICIAN],
        preference,
        "Marie",
    )


async def _machine(db_session, hostname="PC-1", first_seen_days_ago=0, room_id=None):
    from app.features.machine.models import Machine

    m = Machine(
        machine_uuid=str(uuid.uuid4()),
        hostname=hostname,
        first_seen=datetime.now(UTC) - timedelta(days=first_seen_days_ago),
        room_id=uuid.UUID(room_id) if room_id else None,
    )
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return str(m.id)


# --- Assignment ------------------------------------------------------------------


async def test_assigning_a_check_mails_the_assignee_once(
    client, db_session, mailgun_configured
):
    admin, _ = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    m = await _machine(db_session, "PC-B12-03")
    resp = await client.post(
        f"/api/v1/machines/{m}/check",
        headers=admin,
        json={"assigned_to_id": tech_id, "instructions": "Vérifier le câble"},
    )
    assert resp.status_code == 201, resp.text
    queued = await _queued(db_session)
    assert [q.to_address for q in queued] == ["tech@test.local"]
    assert "PC-B12-03" in queued[0].subject
    assert "admin@test.local vous demande" in queued[0].body
    assert "Vérifier le câble" in queued[0].body
    assert "https://tiai.test/#/tasks" in queued[0].body

    # Reassigning to the same person says nothing new; to nobody, nothing.
    check_id = resp.json()["id"]
    await client.patch(
        f"/api/v1/checks/{check_id}", headers=admin, json={"assigned_to_id": tech_id}
    )
    await client.patch(
        f"/api/v1/checks/{check_id}", headers=admin, json={"assigned_to_id": None}
    )
    assert len(await _queued(db_session)) == 1
    # Handed back to Marie: told again.
    await client.patch(
        f"/api/v1/checks/{check_id}", headers=admin, json={"assigned_to_id": tech_id}
    )
    assert len(await _queued(db_session)) == 2


async def test_no_mail_to_oneself_nor_to_an_account_that_wants_none(
    client, db_session, mailgun_configured
):
    admin, admin_id = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session, preference="none")
    a = await _machine(db_session, "A")
    b = await _machine(db_session, "B")
    resp = await client.post(
        f"/api/v1/machines/{a}/check", headers=admin, json={"assigned_to_id": admin_id}
    )
    assert resp.status_code == 201
    resp = await client.post(
        f"/api/v1/machines/{b}/check", headers=admin, json={"assigned_to_id": tech_id}
    )
    assert resp.status_code == 201
    assert await _queued(db_session) == []


async def test_bulk_request_is_one_mail_listing_the_postes(
    client, db_session, mailgun_configured
):
    admin, _ = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    ids = [await _machine(db_session, f"PC-{i}") for i in range(3)]
    resp = await client.post(
        "/api/v1/checks/bulk",
        headers=admin,
        json={
            "machine_ids": ids,
            "assigned_to_id": tech_id,
            "instructions": "Tour de salle",
        },
    )
    assert resp.status_code == 201, resp.text
    queued = await _queued(db_session)
    assert len(queued) == 1
    assert "3 postes" in queued[0].subject
    assert "PC-0" in queued[0].body and "PC-2" in queued[0].body
    assert "Tour de salle" in queued[0].body


# --- The digest's personal block ------------------------------------------------


async def test_digest_ends_with_what_is_mine(client, db_session, mailgun_configured):
    from app.features.notification import digest

    admin, _ = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    # A verification for Marie, and a room she owns with a poste overdue.
    resp = await client.post("/api/v1/rooms", headers=admin, json={"name": "B12"})
    room = resp.json()["id"]
    await client.patch(
        f"/api/v1/rooms/{room}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": tech_id},
    )
    m = await _machine(db_session, "PC-OLD", first_seen_days_ago=200, room_id=room)
    await client.post(
        f"/api/v1/machines/{m}/check",
        headers=admin,
        json={"assigned_to_id": tech_id, "instructions": "Écran"},
    )
    # Clear the assignment mail so the digest is the only row left to read.
    from sqlalchemy import delete

    from app.features.notification.models import EmailOutbox

    await db_session.exec(delete(EmailOutbox))
    await db_session.commit()

    await digest.send_daily_digest(db_session)
    await db_session.commit()
    queued = {q.to_address: q for q in await _queued(db_session)}
    assert set(queued) == {"admin@test.local", "tech@test.local"}
    assert "VOS TÂCHES" in queued["tech@test.local"].body
    assert "Vérifications qui vous sont affectées : 1" in queued["tech@test.local"].body
    assert "PC-OLD — Écran" in queued["tech@test.local"].body
    assert "1 poste(s) en retard" in queued["tech@test.local"].body
    assert "B12" in queued["tech@test.local"].body
    # The admin owns nothing and was handed nothing: no block at all.
    assert "VOS TÂCHES" not in queued["admin@test.local"].body


# --- The weekly reminder ---------------------------------------------------------


async def test_weekly_reminder_goes_to_owners_with_something_due(
    client, db_session, mailgun_configured
):
    from app.features.notification import tasks

    admin, admin_id = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    quiet, _ = await _user(client, db_session, "quiet@test.local", [], "none")
    # Marie owns an overdue poste; the admin owns one that is fine; the quiet
    # account owns an overdue one but asked for no mail.
    a = await _machine(db_session, "A", first_seen_days_ago=200)
    b = await _machine(db_session, "B", first_seen_days_ago=1)
    c = await _machine(db_session, "C", first_seen_days_ago=200)
    await client.patch(
        f"/api/v1/machines/{a}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": tech_id},
    )
    await client.patch(
        f"/api/v1/machines/{b}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": admin_id},
    )
    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    quiet_id = next(u["id"] for u in users if u["email"] == "quiet@test.local")
    await client.patch(
        f"/api/v1/machines/{c}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": quiet_id},
    )

    assert await tasks.send_maintenance_reminders(db_session) == 1
    queued = await _queued(db_session)
    assert [q.to_address for q in queued] == ["tech@test.local"]
    assert "vos maintenances" in queued[0].subject
    assert "A (sans salle) — en retard" in queued[0].body


def test_weekly_schedule_lands_on_the_asked_morning():
    from app.core.worker import weekly_at

    nxt = weekly_at(0, 18)
    # A Wednesday: next Monday 18:00.
    wed = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
    assert nxt(wed) == datetime(2026, 9, 14, 18, 0, tzinfo=UTC)
    # Monday 18:00 sharp: strictly after, so a week later.
    mon = datetime(2026, 9, 14, 18, 0, tzinfo=UTC)
    assert nxt(mon) == datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    # Monday 09:00: today at 18:00.
    assert nxt(datetime(2026, 9, 14, 9, 0, tzinfo=UTC)) == mon
