"""The resolved e-mail policy: the console's rows over the environment, field
by field, and every sender reading it at the moment it sends.

Pure resolution tests need no database; the ones that queue, drain or build a
digest are DB-backed (TIAI_TEST_DATABASE_URL). No mail ever leaves: the
senders are replaced where the outbox imported them.
"""

import uuid

import pytest

from app.core import secretbox
from app.core.config import settings
from app.features.setting import email_policy as mail
from app.features.setting.email_policy import StoredEmailSettings


@pytest.fixture
def env_without_mail(monkeypatch):
    """An environment that sends nothing, whatever the machine running the
    tests has in its own ``.env``: what the console sets is then all there is."""
    for name in (
        "SMTP_HOST",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "MAILGUN_DOMAIN",
        "MAILGUN_API_KEY",
        "EMAIL_FROM_EMAIL",
        "MAILGUN_FROM_EMAIL",
        "EMAIL_FROM_NAME",
    ):
        monkeypatch.setattr(settings, name, None)
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "mailgun")
    monkeypatch.setattr(settings, "MAILGUN_FROM_NAME", "Tia'i")


def _rows(**fields) -> dict:
    """``app_settings`` rows as the table holds them, from API field names;
    secrets are sealed the way ``email_policy.write`` seals them."""
    rows = {}
    for name, value in fields.items():
        if name in mail.SECRET_KEYS:
            rows[mail.SECRET_KEYS[name]] = secretbox.encrypt(value)
        else:
            rows[mail.PLAIN_KEYS[name]] = value
    return rows


# --- Resolution ---------------------------------------------------------------


def test_nothing_stored_is_the_environment(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "relais.lycee.local")
    monkeypatch.setattr(settings, "SMTP_PORT", 25)
    monkeypatch.setattr(settings, "EMAIL_FROM_EMAIL", None)
    # The historical sender name still resolves, as it always did.
    monkeypatch.setattr(settings, "MAILGUN_FROM_EMAIL", "tiai@lycee.local")

    policy = mail.resolve(mail.stored_from({}))

    assert policy.provider == "smtp"
    assert (policy.smtp_host, policy.smtp_port) == ("relais.lycee.local", 25)
    assert policy.from_email == "tiai@lycee.local"
    assert policy.enabled is True


def test_a_stored_field_wins_and_the_others_stay_the_environments(
    env_without_mail, monkeypatch
):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.env.local")
    monkeypatch.setattr(settings, "SMTP_USER", "env-user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "env-password")
    stored = mail.stored_from(
        _rows(
            provider="smtp",
            smtp_port=465,
            smtp_security="tls",
            smtp_password="console-pw",
        )
    )

    policy = mail.resolve(stored)

    assert policy.provider == "smtp"
    assert policy.smtp_port == 465 and policy.smtp_security == "tls"
    assert policy.smtp_password == "console-pw"
    # Not stored: the environment's.
    assert policy.smtp_host == "smtp.env.local"
    assert policy.smtp_user == "env-user"
    # No sender anywhere: SMTP is not complete, and the page says why.
    assert policy.enabled is False
    assert policy.missing() == ["l'adresse d'expéditeur"]


def test_values_a_field_cannot_hold_are_ignored(env_without_mail):
    """A row written by hand or by another version is not trusted blindly."""
    stored = mail.stored_from(
        {
            "email.provider": "sendgrid",
            "email.smtp_port": 0,
            "email.smtp_security": "ssl",
            "email.smtp_verify_tls": "no",
            "email.smtp_timeout_seconds": True,
            "email.smtp_host": "",
            "email.mailgun_api_key": 42,
        }
    )
    assert stored.values == {}
    assert stored.secrets == {} and stored.unreadable == frozenset()
    policy = mail.resolve(stored)
    assert policy.provider == "mailgun"
    assert policy.smtp_port == settings.SMTP_PORT


def test_an_unreadable_secret_is_absent_and_flagged(env_without_mail, monkeypatch):
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-from-env")
    rows = _rows(mailgun_domain="mg.lycee.fr", mailgun_api_key="key-from-console")
    monkeypatch.setattr(settings, "SECRET_KEY", "a-new-secret-key-after-rotation-0123")

    stored = mail.stored_from(rows)

    assert stored.unreadable == frozenset({"mailgun_api_key"})
    assert "mailgun_api_key" not in stored.secrets
    # Absent, so the environment's key applies — never a crash, never garbage.
    assert mail.resolve(stored).mailgun_api_key == "key-from-env"


def test_merged_applies_a_patch_without_writing_it(env_without_mail):
    stored = mail.stored_from(
        _rows(provider="smtp", smtp_host="old.local", smtp_password="pw")
    )
    trial = stored.merged(
        {"smtp_host": "new.local", "provider": None, "smtp_user": "u"}
    )

    assert trial.values == {"smtp_host": "new.local", "smtp_user": "u"}
    # Absent from the patch: the stored secret is kept, not dropped.
    assert trial.secrets == {"smtp_password": "pw"}
    assert stored.values["smtp_host"] == "old.local"  # the original is untouched
    assert stored.merged({"smtp_password": None}).secrets == {}


def test_a_typed_secret_replaces_an_unreadable_one(env_without_mail):
    stored = StoredEmailSettings(unreadable=frozenset({"smtp_password"}))
    assert stored.merged({"smtp_password": "neuf"}).unreadable == frozenset()


def test_secrets_stay_out_of_repr(env_without_mail):
    policy = mail.resolve(
        mail.stored_from(
            _rows(smtp_password="hunter2-smtp", mailgun_api_key="key-hunter2")
        )
    )
    text = repr(policy) + repr(mail.stored_from(_rows(smtp_password="hunter2-smtp")))
    assert "hunter2" not in text


def test_bounded_caps_both_timeouts(env_without_mail, monkeypatch):
    monkeypatch.setattr(settings, "MAILGUN_TIMEOUT_SECONDS", 60)
    policy = mail.resolve(mail.stored_from(_rows(smtp_timeout_seconds=90)))
    capped = policy.bounded(15)
    assert (capped.smtp_timeout_seconds, capped.mailgun_timeout_seconds) == (15, 15)
    assert policy.bounded(120).smtp_timeout_seconds == 90


def test_the_process_remembers_its_last_resolution(env_without_mail):
    assert mail.current_policy().enabled is False
    mail.remember(
        mail.stored_from(_rows(mailgun_domain="mg.x.fr", mailgun_api_key="k"))
    )
    assert mail.current_policy().enabled is True
    mail.forget()
    assert mail.current_policy().enabled is False


# --- Every sender reads the console's settings, without a restart -------------


async def _write(db_session, **fields):
    await mail.write(db_session, fields, actor="admin@test.local")
    await db_session.commit()


async def _outbox(db_session):
    from sqlmodel import select

    from app.features.notification.models import EmailOutbox

    return (await db_session.exec(select(EmailOutbox))).all()


async def test_write_seals_secrets_and_reports_only_that_they_changed(db_session):
    from app.features.setting.crud import get_all

    details = await mail.write(
        db_session,
        {"smtp_password": "Sup3r-s3cret", "smtp_host": "smtp.x.fr", "smtp_user": None},
        actor="admin@test.local",
    )
    await db_session.commit()

    assert details == {
        "email.smtp_host": "smtp.x.fr",
        "email.smtp_password": "modifié",
        "email.smtp_user": None,
    }
    rows = await get_all(db_session)
    assert "Sup3r-s3cret" not in str(rows)
    assert secretbox.decrypt(rows["email.smtp_password"]) == "Sup3r-s3cret"

    details = await mail.write(db_session, {"smtp_password": None}, actor="a")
    assert details == {"email.smtp_password": "effacé"}


async def test_queueing_follows_the_console_once_it_has_been_read(
    db_session, env_without_mail
):
    from app.features.notification.outbox import queue_email

    assert queue_email(db_session, to="a@x.fr", subject="s", text="t") is False

    await _write(db_session, mailgun_domain="mg.x.fr", mailgun_api_key="key-console")
    await mail.load_stored(db_session)
    assert queue_email(db_session, to="a@x.fr", subject="s", text="t") is True
    await db_session.commit()
    assert len(await _outbox(db_session)) == 1


async def test_the_drain_sends_with_the_policy_in_the_database(
    db_session, env_without_mail, monkeypatch
):
    """The worker reads the settings at every drain: a password typed in the
    console after the worker started is the one it sends with."""
    from app.features.notification import outbox
    from app.features.notification.models import EmailOutbox

    db_session.add(EmailOutbox(to_address="a@x.fr", subject="s", body="t"))
    await db_session.commit()
    await _write(
        db_session,
        provider="smtp",
        smtp_host="smtp.console.fr",
        from_email="tiai@x.fr",
        smtp_password="typed-in-console",
    )
    used = []

    async def _capture(subject, text, to, *, policy):
        used.append(policy)
        return True

    monkeypatch.setattr(outbox, "send_email", _capture)
    assert await outbox.send_pending(db_session) == 1
    (policy,) = used
    assert (policy.provider, policy.smtp_host) == ("smtp", "smtp.console.fr")
    assert policy.smtp_password == "typed-in-console"


async def test_the_digest_goes_out_when_only_the_console_configures_mail(
    db_session, env_without_mail
):
    from app.features.notification.digest import send_daily_digest
    from app.features.user import crud

    await crud.create_user(db_session, email="op@x.fr", password="pw-not-used-here")
    await db_session.commit()
    # Nothing configured anywhere: nothing queued.
    assert await send_daily_digest(db_session) == 0

    await _write(
        db_session, provider="smtp", smtp_host="smtp.x.fr", from_email="tiai@x.fr"
    )
    # The worker process has never resolved the policy since: the digest
    # reads it itself.
    mail.forget()
    assert await send_daily_digest(db_session) == 1
    assert [r.to_address for r in await _outbox(db_session)] == ["op@x.fr"]


async def test_the_threat_alert_reads_the_console_too(db_session, env_without_mail):
    from app.features.notification.threat_alert import (
        MachineContext,
        queue_threat_alert,
    )
    from app.features.threat.crud import NewDetection
    from app.features.user import crud
    from app.features.user.models import EmailPreference

    user = await crud.create_user(
        db_session, email="vigie@x.fr", password="pw-not-used-here"
    )
    user.email_preference = EmailPreference.IMMEDIATE
    db_session.add(user)
    await db_session.commit()

    machine = MachineContext(
        id=uuid.uuid4(),
        machine_uuid="m-1",
        hostname="PC-1",
        domain=None,
        ip_address=None,
        session_username=None,
    )
    detection = NewDetection(
        detection_id="d-1",
        threat_name="EICAR",
        severity="high",
        status="active",
        detected_at=None,
    )
    assert await queue_threat_alert(db_session, machine, [detection]) == 0

    await _write(db_session, mailgun_domain="mg.x.fr", mailgun_api_key="key-console")
    mail.forget()
    assert await queue_threat_alert(db_session, machine, [detection]) == 1
