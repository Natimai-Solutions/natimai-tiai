"""The card « Envoi des e-mails »: GET/PATCH /settings and the test send.

DB-backed: requires TIAI_TEST_DATABASE_URL. Nothing leaves the machine:
smtplib and Mailgun's HTTP client are replaced by recorders.
"""

import smtplib
import socket

import httpx
import pytest

from app.core import secretbox
from app.core.config import settings
from app.features.notification import mailgun, smtp

STRONG = "correct-horse-battery"


@pytest.fixture(autouse=True)
def env_without_mail(monkeypatch):
    """The environment sends nothing: whatever works below, the console made
    it work."""
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


@pytest.fixture(autouse=True)
def _fresh_test_send_budget():
    """The test-send limiter is process-global like the login one: every test
    here sends from the same client address."""
    from app.api.routes.settings_routes import email_test_limiter

    email_test_limiter.reset()
    yield
    email_test_limiter.reset()


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout, context=None) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.login_args = None
        self.sent = None
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, context=None) -> None:
        pass

    def login(self, user, password) -> None:
        self.login_args = (user, password)
        if type(self).fail_with is not None:
            raise type(self).fail_with

    def send_message(self, msg) -> dict:
        self.sent = msg
        return {}


@pytest.fixture
def fake_smtp(monkeypatch):
    _FakeSMTP.instances = []
    _FakeSMTP.fail_with = None
    monkeypatch.setattr(smtp.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtp.smtplib, "SMTP_SSL", _FakeSMTP)
    return _FakeSMTP


def _mailgun_answering(monkeypatch, status: int) -> list[dict]:
    calls: list[dict] = []

    class _Client:
        def __init__(self, **kwargs) -> None:
            calls.append({"init": kwargs})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return httpx.Response(status, request=httpx.Request("POST", url))

    monkeypatch.setattr(mailgun.httpx, "AsyncClient", _Client)
    return calls


async def _login(client, db_session, email, groups):
    from app.features.user import crud

    await crud.create_user(db_session, email=email, password=STRONG, groups=groups)
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": STRONG}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _admin(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    return await _login(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])


async def _patch(client, headers, **email):
    resp = await client.patch(
        "/api/v1/settings", headers=headers, json={"email": email}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["email"]


async def _audit(db_session, action):
    from sqlmodel import col, select

    from app.features.audit.models import AuditEntry

    rows = await db_session.exec(
        select(AuditEntry)
        .where(col(AuditEntry.action) == action)
        .order_by(col(AuditEntry.at))
    )
    return rows.all()


# --- GET / PATCH --------------------------------------------------------------


async def test_get_shows_the_environment_and_nothing_stored(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "env-smtp-password")
    monkeypatch.setattr(settings, "SMTP_USER", "env-account@x.fr")
    admin = await _admin(client, db_session)

    resp = await client.get("/api/v1/settings", headers=admin)

    assert resp.status_code == 200
    email = resp.json()["email"]
    assert email["provider"] is None and email["smtp_host"] is None
    assert email["smtp_password_set"] is False
    assert email["configured"] is False
    assert email["missing"] == ["le domaine Mailgun", "la clé API Mailgun"]
    assert email["env"]["provider"] == "mailgun"
    assert email["env"]["smtp_password_set"] is True
    assert email["env"]["smtp_user_set"] is True
    # Whether the environment holds credentials, never what they are.
    assert "env-smtp-password" not in resp.text
    assert "env-account@x.fr" not in resp.text


async def test_patch_stores_fields_and_seals_the_secret(client, db_session):
    from app.features.setting.crud import get_all

    admin = await _admin(client, db_session)
    email = await _patch(
        client,
        admin,
        provider="smtp",
        smtp_host=" smtp.office365.com ",
        smtp_port=587,
        smtp_security="starttls",
        smtp_user="tiai@lycee.fr",
        smtp_password="Pa55-word-SMTP",
        from_email="tiai@lycee.fr",
        from_name="Tia'i du lycée",
    )

    assert email["provider"] == "smtp" and email["effective_provider"] == "smtp"
    assert email["smtp_host"] == "smtp.office365.com"  # trimmed
    assert email["smtp_user"] == "tiai@lycee.fr"
    assert email["smtp_password_set"] is True
    assert email["smtp_password_unreadable"] is False
    assert email["configured"] is True and email["missing"] == []
    assert "smtp_password" not in email

    rows = await get_all(db_session)
    assert "Pa55-word-SMTP" not in str(rows)
    assert secretbox.decrypt(rows["email.smtp_password"]) == "Pa55-word-SMTP"

    (entry,) = await _audit(db_session, "settings.update")
    assert entry.details["email.smtp_password"] == "modifié"
    assert entry.details["email.smtp_host"] == "smtp.office365.com"
    assert "Pa55-word-SMTP" not in str(entry.details)

    # Absent = unchanged: a patch of the port keeps the stored password.
    email = await _patch(client, admin, smtp_port=465, smtp_security="tls")
    assert email["smtp_port"] == 465 and email["smtp_password_set"] is True

    # Null = forget it, the environment's applies again; so does an empty box.
    email = await _patch(client, admin, smtp_password=None, smtp_host="")
    assert email["smtp_password_set"] is False
    assert email["smtp_host"] is None
    assert email["configured"] is False
    assert email["missing"] == ["le serveur SMTP"]
    last = (await _audit(db_session, "settings.update"))[-1]
    assert last.details["email.smtp_password"] == "effacé"


async def test_a_secret_sealed_under_an_old_key_must_be_typed_again(client, db_session):
    from cryptography.fernet import Fernet

    from app.features.setting.crud import set_value

    admin = await _admin(client, db_session)
    await _patch(client, admin, mailgun_domain="mg.x.fr", mailgun_api_key="key-old")
    # What a SECRET_KEY rotation leaves behind: a token sealed under a key the
    # server no longer derives. (Rotating the key itself here would also void
    # the test's own session token.)
    foreign = Fernet(Fernet.generate_key()).encrypt(b"key-old").decode()
    await set_value(db_session, "email.mailgun_api_key", foreign, actor="before")
    await db_session.commit()

    resp = await client.get("/api/v1/settings", headers=admin)

    assert resp.status_code == 200
    email = resp.json()["email"]
    assert email["mailgun_api_key_set"] is False
    assert email["mailgun_api_key_unreadable"] is True
    assert email["configured"] is False

    email = await _patch(client, admin, mailgun_api_key="key-new")
    assert email["mailgun_api_key_set"] is True
    assert email["mailgun_api_key_unreadable"] is False
    assert email["configured"] is True


@pytest.mark.parametrize(
    "field",
    [
        {"smtp_port": 0},
        {"smtp_port": 65536},
        {"smtp_security": "ssl"},
        {"provider": "sendgrid"},
        {"from_email": "pas-une-adresse"},
        {"smtp_host": "smtp.x.fr/chemin"},
        {"mailgun_base_url": "ftp://api.mailgun.net"},
        {"smtp_timeout_seconds": 0},
        # An untouched password box must not be able to wipe the password.
        {"smtp_password": ""},
    ],
)
async def test_patch_refuses_what_cannot_work(client, db_session, field):
    admin = await _admin(client, db_session)
    resp = await client.patch("/api/v1/settings", headers=admin, json={"email": field})
    assert resp.status_code == 422, resp.text


async def test_mail_settings_are_admin_material(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    tech = await _login(
        client, db_session, "tech@test.local", [BuiltinGroup.TECHNICIAN]
    )
    resp = await client.patch(
        "/api/v1/settings", headers=tech, json={"email": {"provider": "smtp"}}
    )
    assert resp.status_code == 403
    resp = await client.post("/api/v1/settings/email/test", headers=tech, json={})
    assert resp.status_code == 403


async def test_a_patch_applies_to_the_next_queued_mail(client, db_session):
    """No restart: the API process's queueing guard sees the new settings."""
    from app.features.notification.outbox import queue_email

    admin = await _admin(client, db_session)
    assert queue_email(db_session, to="a@x.fr", subject="s", text="t") is False
    await _patch(client, admin, mailgun_domain="mg.x.fr", mailgun_api_key="key-1")
    assert queue_email(db_session, to="a@x.fr", subject="s", text="t") is True


# --- Test send ------------------------------------------------------------------


async def test_test_send_uses_the_stored_smtp_settings(client, db_session, fake_smtp):
    admin = await _admin(client, db_session)
    await _patch(
        client,
        admin,
        provider="smtp",
        smtp_host="smtp.x.fr",
        from_email="tiai@x.fr",
        smtp_user="tiai@x.fr",
        smtp_password="pw-stored",
        smtp_timeout_seconds=90,
    )

    resp = await client.post("/api/v1/settings/email/test", headers=admin, json={})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert "admin@test.local" in body["message"]
    (session,) = fake_smtp.instances
    assert session.host == "smtp.x.fr"
    assert session.login_args == ("tiai@x.fr", "pw-stored")
    assert session.timeout == 15  # bounded, whatever the stored timeout
    assert session.sent["To"] == "admin@test.local"

    # Sent now, not queued: the outbox stays empty.
    from sqlmodel import select

    from app.features.notification.models import EmailOutbox

    assert (await db_session.exec(select(EmailOutbox))).all() == []
    (entry,) = await _audit(db_session, "settings.email_test")
    assert entry.details["ok"] == "oui"
    assert entry.details["to"] == "admin@test.local"
    assert "pw-stored" not in str(entry.details)


async def test_test_send_tries_unsaved_values_without_saving_them(
    client, db_session, fake_smtp
):
    from app.features.setting.crud import get_all

    admin = await _admin(client, db_session)
    await _patch(
        client,
        admin,
        provider="smtp",
        smtp_host="old.x.fr",
        from_email="tiai@x.fr",
        smtp_user="tiai@x.fr",
        smtp_password="pw-stored",
    )

    resp = await client.post(
        "/api/v1/settings/email/test",
        headers=admin,
        json={
            "to": "autre@x.fr",
            "email": {"smtp_host": "new.x.fr", "smtp_port": 2525},
        },
    )

    assert resp.json()["ok"] is True
    (session,) = fake_smtp.instances
    assert (session.host, session.port) == ("new.x.fr", 2525)
    # The stored password was used without being typed again.
    assert session.login_args == ("tiai@x.fr", "pw-stored")
    assert session.sent["To"] == "autre@x.fr"
    rows = await get_all(db_session)
    assert rows["email.smtp_host"] == "old.x.fr"
    assert "email.smtp_port" not in rows
    (entry,) = await _audit(db_session, "settings.email_test")
    assert entry.details["unsaved"] == "smtp_host, smtp_port"


async def test_test_send_reports_an_smtp_refusal_in_words(
    client, db_session, fake_smtp
):
    admin = await _admin(client, db_session)
    fake_smtp.fail_with = smtplib.SMTPAuthenticationError(
        535, b"5.7.3 Authentication unsuccessful"
    )

    resp = await client.post(
        "/api/v1/settings/email/test",
        headers=admin,
        json={
            "email": {
                "provider": "smtp",
                "smtp_host": "smtp.x.fr",
                "from_email": "tiai@x.fr",
                "smtp_user": "tiai@x.fr",
                "smtp_password": "wrong-password",
            }
        },
    )

    body = resp.json()
    assert resp.status_code == 200
    assert body["ok"] is False
    assert body["message"].startswith("Identifiants refusés")
    assert "535" in body["message"]
    assert "wrong-password" not in body["message"]
    (entry,) = await _audit(db_session, "settings.email_test")
    assert entry.details["ok"] == "non"
    assert "wrong-password" not in str(entry.details)


async def test_test_send_with_an_incomplete_configuration(client, db_session):
    admin = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/settings/email/test",
        headers=admin,
        json={"email": {"provider": "smtp"}},
    )
    body = resp.json()
    assert body["ok"] is False
    assert body["message"] == (
        "Configuration incomplète : il manque le serveur SMTP, l'adresse d'expéditeur."
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, None),
        (401, "Clé API Mailgun refusée (401)"),
        (404, "Mailgun ne connaît pas le domaine mg.x.fr (404)"),
        (500, "Mailgun a répondu 500"),
    ],
)
async def test_test_send_through_mailgun(
    client, db_session, monkeypatch, status, expected
):
    monkeypatch.setattr(settings, "MAILGUN_TIMEOUT_SECONDS", 60)
    calls = _mailgun_answering(monkeypatch, status)
    admin = await _admin(client, db_session)
    await _patch(
        client,
        admin,
        mailgun_domain="mg.x.fr",
        mailgun_api_key="key-console",
        mailgun_base_url="https://api.eu.mailgun.net/v3/",
        from_email="tiai@x.fr",
    )

    body = (
        await client.post("/api/v1/settings/email/test", headers=admin, json={})
    ).json()

    init, post = calls
    assert init["init"]["timeout"] == 15
    assert post["url"] == "https://api.eu.mailgun.net/v3/mg.x.fr/messages"
    assert post["auth"] == ("api", "key-console")
    if expected is None:
        assert body["ok"] is True
    else:
        assert body["ok"] is False
        assert body["message"].startswith(expected)


async def test_the_test_send_is_rate_limited(client, db_session):
    admin = await _admin(client, db_session)
    statuses = [
        (
            await client.post("/api/v1/settings/email/test", headers=admin, json={})
        ).status_code
        for _ in range(11)
    ]
    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429


# --- Error wording (no network) -------------------------------------------------


def _smtp_policy():
    from app.features.setting import email_policy as mail

    return mail.resolve(
        mail.StoredEmailSettings(
            values={
                "provider": "smtp",
                "smtp_host": "smtp.x.fr",
                "from_email": "t@x.fr",
            },
            secrets={"smtp_password": "hunter2-secret"},
        )
    )


@pytest.mark.parametrize(
    ("exc", "start"),
    [
        (
            smtplib.SMTPSenderRefused(553, b"not owner", "t@x.fr"),
            "Adresse d'expéditeur",
        ),
        (
            smtplib.SMTPRecipientsRefused({"a@x.fr": (550, b"no such user")}),
            "Destinataire refusé",
        ),
        (
            smtplib.SMTPNotSupportedError("STARTTLS extension not supported"),
            "Le serveur SMTP ne propose pas",
        ),
        (smtplib.SMTPServerDisconnected("closed"), "Le serveur smtp.x.fr:587 a fermé"),
        (
            smtplib.SMTPDataError(554, b"rejected"),
            "Le serveur SMTP a répondu par une erreur : 554",
        ),
        (smtplib.SMTPException("odd"), "Erreur SMTP"),
        (socket.gaierror(-2, "Name or service not known"), "Serveur SMTP introuvable"),
        (
            ConnectionRefusedError(111, "Connection refused"),
            "Connexion refusée par smtp.x.fr:587",
        ),
        (TimeoutError(), "Le serveur smtp.x.fr:587 n'a pas répondu"),
        (OSError(101, "Network is unreachable"), "Impossible de joindre smtp.x.fr:587"),
        (httpx.ConnectTimeout("t"), "Mailgun n'a pas répondu"),
        (httpx.ConnectError("refused"), "Impossible de joindre Mailgun"),
        (ValueError("hunter2-secret leaked"), "Erreur inattendue"),
    ],
)
def test_errors_read_as_what_to_fix(exc, start):
    from app.features.notification import probe

    policy = _smtp_policy()
    message = probe._scrub(probe.describe_error(exc, policy), policy)
    assert message.startswith(start), message
    assert "hunter2-secret" not in message


def test_tls_errors_point_at_the_security_mode():
    import ssl

    from app.features.notification import probe

    policy = _smtp_policy()
    cert = ssl.SSLCertVerificationError(1, "certificate verify failed")
    cert.verify_message = "self-signed certificate"
    assert "Certificat du serveur" in probe.describe_error(cert, policy)
    assert "STARTTLS sur 587" in probe.describe_error(
        ssl.SSLError(1, "wrong version number"), policy
    )
