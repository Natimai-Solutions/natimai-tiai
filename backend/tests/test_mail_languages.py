"""Every mail in its reader's language (plan ``dev/plan-console-bilingue.md``, I4).

The French of each mail is pinned word for word — subject and body — by
``tests/data/mail_texts.json``: it was captured from the mails as they read
before they learnt English, and an installation that sets nothing must keep
receiving exactly those. The English beside it is pinned the same way.

The rendering cases are pure (no database) except the weekly reminder, which
reads the « VOS TÂCHES » block off real rows, and the routing tests at the
end (who gets which language), which require TIAI_TEST_DATABASE_URL.
"""

import dataclasses
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.features.user.models import Language

GOLDEN = json.loads(
    (Path(__file__).parent / "data" / "mail_texts.json").read_text(encoding="utf-8")
)
NOW = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)
STRONG = "correct-horse-battery"


@pytest.fixture
def mail_settings(monkeypatch):
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.test.local")
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-test")
    monkeypatch.setattr(settings, "CONSOLE_BASE_URL", "https://tiai.test")
    monkeypatch.setattr(settings, "NOTIFICATION_MAX_ITEMS", 2)


def _assert_golden(case: str, language: Language, subject: str, body: str) -> None:
    expected = GOLDEN[case][language.value]
    assert subject == expected["subject"]
    assert body.split("\n") == expected["body"]


# --- The cases ------------------------------------------------------------------


def _digest(**changes):
    from app.features.notification import digest as d

    quiet = d.Digest(
        generated_at=NOW,
        total=1,
        online=0,
        with_active_threats=0,
        with_high_severity_updates=0,
        needs_verification=0,
        new_threats_24h=0,
        outdated_antivirus=0,
        wu_pending=0,
        reboot_required=0,
        inactive=0,
    )
    return dataclasses.replace(quiet, **changes)


def _digest_events(language):
    from app.features.notification import digest as d

    full = _digest(
        total=42,
        online=17,
        with_active_threats=3,
        with_high_severity_updates=2,
        needs_verification=1,
        new_threats_24h=4,
        outdated_antivirus=5,
        wu_pending=6,
        reboot_required=2,
        inactive=7,
        threat_lines=[
            d.MachineLine("PC-A", d._threats_detail(2)),
            d.MachineLine("PC-B", d._threats_detail(1)),
        ],
        update_lines=[d.MachineLine("PC-C", d._updates_detail(3))],
        outdated_lines=[
            d.MachineLine("PC-D", d._antivirus_detail(12)),
            d.MachineLine("PC-E", d._antivirus_detail(None)),
        ],
    )
    return d.render_digest(full, ["VOS TÂCHES", "  (bloc)", ""], language)


def _render_digest(**changes):
    def render(language):
        from app.features.notification import digest as d

        return d.render_digest(_digest(**changes), None, language)

    return render


def _tasks_digest(language):
    from app.features.notification import digest as d

    return d.render_tasks_digest(["VOS TÂCHES", "  (bloc)", ""], NOW, language)


def _detections():
    from app.features.threat.crud import NewDetection

    return [
        NewDetection("a", "Trojan:Win32/Test", "Severe", "Active", NOW),
        NewDetection("b", None, None, None, None),
        NewDetection("c", "Other", None, None, None),
    ]


def _alert_many(language):
    from app.features.notification.threat_alert import MachineContext, render_alert

    machine = MachineContext(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        machine_uuid="uuid-1",
        hostname="PC-042",
        domain="LYCEE",
        ip_address="10.0.0.4",
        session_username="eleve",
    )
    return render_alert(machine, _detections(), language)


def _alert_one(language):
    from app.features.notification.threat_alert import MachineContext, render_alert

    bare = MachineContext(
        id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        machine_uuid="uuid-2",
        hostname=None,
        domain=None,
        ip_address=None,
        session_username=None,
    )
    return render_alert(bare, _detections()[:1], language)


def _captured(monkeypatch, module) -> dict[str, tuple[str, str]]:
    captured: dict[str, tuple[str, str]] = {}

    def fake_queue(session, *, to, subject, text):
        captured["mail"] = (subject, text)
        return True

    monkeypatch.setattr(module, "queue_email", fake_queue)
    return captured


def _password_reset(language, monkeypatch):
    from app.features.user import emails

    captured = _captured(monkeypatch, emails)
    assert emails.send_password_reset(
        None, "a@test.local", "tok123", language=language.value
    )
    return captured["mail"]


def _check(machines, requested_by, instructions):
    def render(language, monkeypatch):
        from app.features.machine.models import Machine
        from app.features.notification import tasks
        from app.features.user.models import User

        captured = _captured(monkeypatch, tasks)
        assignee = User(
            email="marie@test.local", hashed_password="x", language=language.value
        )
        assert tasks.send_checks_assigned(
            None,
            assignee=assignee,
            machines=[
                Machine(machine_uuid=f"u-{i}", hostname=name)
                for i, name in enumerate(machines)
            ],
            requested_by=requested_by,
            instructions=instructions,
        )
        return captured["mail"]

    return render


def _policy(**values):
    from app.features.setting import email_policy as mail

    return mail.resolve(
        mail.StoredEmailSettings(values={"from_email": "tiai@lycee.local", **values})
    )


def _test_mail(policy):
    def render(language):
        from app.features.notification.probe_texts import probe_mail

        return probe_mail(policy(), language)

    return render


def _approval(kind="command", outcome=None, **changes):
    def render(language):
        from app.features.notification import approval_mail

        view = approval_mail.RequestView(
            kind=kind,
            command_type="package_install" if kind == "command" else "reboot",
            package_name="7-Zip 23.01" if kind == "command" else None,
            target_kind="domain" if kind == "command" else "room",
            target_value="LYCEE" if kind == "command" else "B12",
            count=45,
            threshold=40,
            expires_at=NOW + timedelta(hours=24),
            requested_by="marie@test.local",
            schedule_name="Redémarrage du soir" if kind == "schedule" else None,
            **changes,
        )
        if outcome is None:
            return approval_mail.render_request(view, language)
        rendered = approval_mail.render_outcome(view, language)
        assert rendered is not None
        return rendered

    return render


PURE: dict[str, Callable] = {
    "approval_request": _approval(),
    "approval_request_schedule": _approval(kind="schedule"),
    "approval_approved": _approval(
        outcome=True,
        status="approved",
        decided_by="jean@test.local",
        created=40,
        skipped=3,
        left_out=2,
    ),
    "approval_rejected": _approval(
        kind="schedule",
        outcome=True,
        status="rejected",
        decided_by="jean@test.local",
        note="Pas pendant les examens",
    ),
    "approval_expired": _approval(outcome=True, status="expired"),
    "approval_failed": _approval(
        outcome=True,
        status="failed",
        decided_by="jean@test.local",
        result_code="permission_lost",
        result_params={"permission": "risky_command:execute"},
    ),
    "digest_events": _digest_events,
    "digest_quiet": _render_digest(),
    "digest_updates": _render_digest(with_high_severity_updates=1),
    "digest_verify": _render_digest(needs_verification=2),
    "tasks_digest": _tasks_digest,
    "alert_many": _alert_many,
    "alert_one": _alert_one,
    "test_mail_smtp": _test_mail(
        lambda: _policy(provider="smtp", smtp_host="smtp.lycee.local", smtp_port=587)
    ),
    "test_mail_mailgun": _test_mail(
        lambda: dataclasses.replace(
            _policy(provider="mailgun", mailgun_domain="mg.lycee.local"),
            mailgun_api_key="key-x",
        )
    ),
}
QUEUED: dict[str, Callable] = {
    "password_reset": _password_reset,
    "check_one": _check(["PC-B12-03"], "admin@test.local", "Écran\nClavier"),
    "check_many": _check(["PC-3", "PC-1", "PC-2"], "Jean", None),
}


@pytest.mark.parametrize("language", list(Language))
@pytest.mark.parametrize("case", sorted(PURE))
def test_a_mail_reads_as_pinned(case, language, mail_settings):
    _assert_golden(case, language, *PURE[case](language))


@pytest.mark.parametrize("language", list(Language))
@pytest.mark.parametrize("case", sorted(QUEUED))
def test_a_queued_mail_reads_as_pinned(case, language, mail_settings, monkeypatch):
    _assert_golden(case, language, *QUEUED[case](language, monkeypatch))


def test_every_case_is_pinned_in_both_languages():
    assert set(GOLDEN) == set(PURE) | set(QUEUED) | {"reminder"}
    for case, texts in GOLDEN.items():
        assert set(texts) == {"fr", "en"}, case


def test_the_digests_named_postes_are_worded_per_reader():
    """One digest is built per scope and read in several languages: the
    reason a poste is listed is worded when the mail is."""
    from app.features.notification import digest as d
    from app.features.notification.digest_texts import EN, FR

    line = d.MachineLine("PC-A", d._antivirus_detail(1))
    assert line.worded(FR) == "signatures vieilles de 1 j"
    assert line.worded(EN) == "signatures 1 day old"
    # A detail already in words — an older caller — is printed as it is.
    assert d.MachineLine("PC-B", "texte").worded(EN) == "texte"


# --- Which language --------------------------------------------------------------


def test_the_language_is_the_accounts_else_the_default(monkeypatch):
    from app.features.notification.language import mail_language

    assert mail_language("en") is Language.EN
    assert mail_language("fr") is Language.FR
    assert mail_language(None) is Language.FR
    # A value written by hand that is not a language reads as no choice.
    assert mail_language("de") is Language.FR
    monkeypatch.setattr(settings, "DEFAULT_LANGUAGE", "en")
    assert mail_language(None) is Language.EN
    assert mail_language("fr") is Language.FR


def test_a_mail_without_a_language_is_in_the_default_one(monkeypatch, mail_settings):
    from app.features.notification import digest as d

    subject, _ = d.render_digest(_digest())
    assert subject == GOLDEN["digest_quiet"]["fr"]["subject"]
    monkeypatch.setattr(settings, "DEFAULT_LANGUAGE", "en")
    subject, _ = d.render_digest(_digest())
    assert subject == GOLDEN["digest_quiet"]["en"]["subject"]


# --- DB-backed --------------------------------------------------------------------


async def _user(client, db_session, email, groups, preference, language=None):
    from app.features.user import crud

    user = await crud.create_user(
        db_session, email=email, password=STRONG, groups=groups
    )
    user_id = str(user.id)
    user.email_preference = preference
    user.language = language
    db_session.add(user)
    await db_session.commit()
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": STRONG}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user_id


async def _machine(db_session, hostname, days, room_id=None):
    from app.features.machine.models import Machine

    m = Machine(
        machine_uuid=str(uuid.uuid4()),
        hostname=hostname,
        first_seen=datetime.now(UTC) - timedelta(days=days),
        room_id=uuid.UUID(room_id) if room_id else None,
    )
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return str(m.id)


async def _outbox(db_session):
    from sqlmodel import col, select

    from app.features.notification.models import EmailOutbox

    rows = await db_session.exec(
        select(EmailOutbox).order_by(col(EmailOutbox.to_address))
    )
    return {row.to_address: row for row in rows.all()}


async def _clear_outbox(db_session):
    from sqlalchemy import delete

    from app.features.notification.models import EmailOutbox

    await db_session.exec(delete(EmailOutbox))
    await db_session.commit()


@pytest.mark.parametrize("language", list(Language))
async def test_the_weekly_reminder_reads_as_pinned(
    client, db_session, mail_settings, language
):
    """The « VOS TÂCHES » block off real rows: verifications (one with
    instructions over two lines), a room and postes without one, overflow."""
    from app.features.notification import tasks
    from app.features.user.permissions import BuiltinGroup

    admin, _ = await _user(
        client, db_session, "admin@test.local", [BuiltinGroup.ADMIN], "none"
    )
    _, tech_id = await _user(
        client,
        db_session,
        "tech@test.local",
        [BuiltinGroup.TECHNICIAN],
        "immediate",
        language.value,
    )
    resp = await client.post("/api/v1/buildings", headers=admin, json={"name": "Bât A"})
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/rooms",
        headers=admin,
        json={"name": "B12", "building_id": resp.json()["id"]},
    )
    assert resp.status_code == 201, resp.text
    room = resp.json()["id"]
    await client.patch(
        f"/api/v1/rooms/{room}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": tech_id},
    )
    old = await _machine(db_session, "PC-OLD", 200, room)
    await _machine(db_session, "PC-OLD2", 200, room)
    for name in ("PC-LOOSE", "PC-LOOSE2"):
        loose = await _machine(db_session, name, 200)
        await client.patch(
            f"/api/v1/machines/{loose}/maintenance",
            headers=admin,
            json={"maintenance_owner_id": tech_id},
        )
    extra = await _machine(db_session, "PC-X", 1)
    for machine_id, instructions in (
        (old, "Écran\nClavier"),
        (loose, None),
        (extra, None),
    ):
        resp = await client.post(
            f"/api/v1/machines/{machine_id}/check",
            headers=admin,
            json={"assigned_to_id": tech_id, "instructions": instructions},
        )
        assert resp.status_code == 201, resp.text
    await _clear_outbox(db_session)

    assert await tasks.send_maintenance_reminders(db_session) == 1
    mail = (await _outbox(db_session))["tech@test.local"]
    date = tasks.mail_date(datetime.now(UTC))
    expected = GOLDEN["reminder"][language.value]
    assert mail.subject == expected["subject"].replace("{date}", date)
    assert mail.body.split("\n") == expected["body"]


async def test_the_digest_goes_out_in_each_readers_language(
    client, db_session, mail_settings, monkeypatch
):
    """One parc, read by three accounts: the one who chose English, the one
    who chose French, the one who chose nothing — who follows
    DEFAULT_LANGUAGE."""
    from app.features.notification import digest
    from app.features.user.permissions import BuiltinGroup

    for email, language in (
        ("en@test.local", "en"),
        ("fr@test.local", "fr"),
        ("none@test.local", None),
    ):
        await _user(
            client, db_session, email, [BuiltinGroup.ADMIN], "digest_daily", language
        )
    await _machine(db_session, "PC-1", 1)

    await digest.send_daily_digest(db_session)
    mails = await _outbox(db_session)
    assert "fleet on" in mails["en@test.local"].subject
    assert "CURRENT STATE" in mails["en@test.local"].body
    assert "parc du" in mails["fr@test.local"].subject
    assert "ÉTAT COURANT" in mails["fr@test.local"].body
    assert "parc du" in mails["none@test.local"].subject

    await _clear_outbox(db_session)
    monkeypatch.setattr(settings, "DEFAULT_LANGUAGE", "en")
    await digest.send_daily_digest(db_session)
    mails = await _outbox(db_session)
    assert "fleet on" in mails["none@test.local"].subject
    assert "parc du" in mails["fr@test.local"].subject


async def test_a_threat_alert_is_written_once_per_language(
    client, db_session, mail_settings, monkeypatch
):
    from app.features.base import utcnow
    from app.features.machine.models import Machine
    from app.features.notification import threat_alert
    from app.features.user.permissions import BuiltinGroup

    for email, language in (
        ("a-en@test.local", "en"),
        ("b-en@test.local", "en"),
        ("c-fr@test.local", None),
    ):
        await _user(
            client, db_session, email, [BuiltinGroup.ADMIN], "immediate", language
        )
    machine = Machine(machine_uuid="uuid-alert", hostname="PC-7")
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)

    rendered: list[Language | None] = []
    original = threat_alert.render_alert

    def counting(machine, detections, language=None):
        rendered.append(language)
        return original(machine, detections, language)

    monkeypatch.setattr(threat_alert, "render_alert", counting)
    # Dated now: the alert leaves out detections older than
    # THREAT_ALERT_MAX_AGE_HOURS, and the fixed NOW above ages with the clock.
    from app.features.threat.crud import NewDetection

    fresh = [NewDetection("a", "Trojan:Win32/Test", "Severe", "Active", utcnow())]
    queued = await threat_alert.queue_threat_alert(
        db_session, threat_alert.MachineContext.of(machine), fresh
    )
    await db_session.commit()

    assert queued == 3
    assert sorted(rendered) == [Language.EN, Language.FR]
    mails = await _outbox(db_session)
    assert mails["a-en@test.local"].subject.endswith("threat detected on PC-7")
    assert mails["b-en@test.local"].subject == mails["a-en@test.local"].subject
    assert mails["c-fr@test.local"].subject.endswith("menace détectée sur PC-7")


async def test_a_reset_link_is_mailed_in_the_accounts_language(
    client, db_session, mail_settings
):
    await _user(client, db_session, "en@test.local", [], "none", "en")
    await _user(client, db_session, "fr@test.local", [], "none", None)
    for email in ("en@test.local", "fr@test.local"):
        resp = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": email}
        )
        assert resp.status_code == 204
    mails = await _outbox(db_session)
    assert mails["en@test.local"].subject == "Tia'i — password reset"
    assert mails["fr@test.local"].subject == (
        "Tia'i — réinitialisation du mot de passe"
    )


async def test_a_check_is_announced_in_the_assignees_language(
    client, db_session, mail_settings
):
    from app.features.user.permissions import BuiltinGroup

    admin, _ = await _user(
        client, db_session, "admin@test.local", [BuiltinGroup.ADMIN], "none"
    )
    _, tech_id = await _user(
        client,
        db_session,
        "tech@test.local",
        [BuiltinGroup.TECHNICIAN],
        "digest_daily",
        "en",
    )
    machine = await _machine(db_session, "PC-9", 1)
    resp = await client.post(
        f"/api/v1/machines/{machine}/check",
        headers=admin,
        json={"assigned_to_id": tech_id},
    )
    assert resp.status_code == 201, resp.text
    mail = (await _outbox(db_session))["tech@test.local"]
    assert mail.subject == "Tia'i — check requested: PC-9"
    assert mail.body.startswith("admin@test.local asks you to check the computer PC-9.")


@pytest.mark.parametrize(
    ("language", "subject"),
    [("en", "Tia'i — test e-mail"), (None, "Tia'i — e-mail de test")],
)
async def test_the_test_mail_is_in_the_language_of_who_asked(
    client, db_session, monkeypatch, language, subject
):
    """The administrator's language, else DEFAULT_LANGUAGE; the result the
    page shows is not the mail and is left as it is."""
    from app.features.notification import probe
    from app.features.user.permissions import BuiltinGroup

    sent: list[tuple[str, str]] = []

    async def fake_send(subject, text, to, *, policy):
        sent.append((subject, text))
        return True

    monkeypatch.setattr(probe, "send_email", fake_send)
    admin, _ = await _user(
        client, db_session, "admin@test.local", [BuiltinGroup.ADMIN], "none", language
    )
    resp = await client.post(
        "/api/v1/settings/email/test",
        headers=admin,
        json={
            "email": {
                "provider": "smtp",
                "smtp_host": "smtp.lycee.local",
                "from_email": "tiai@lycee.local",
            }
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert [s for s, _ in sent] == [subject]
