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

    # Absent = unchanged: a patch of the sender keeps the stored password.
    email = await _patch(client, admin, from_name="Tia'i")
    assert email["smtp_password_set"] is True
    # But the password does not follow a new port or security mode unless it
    # is typed again (audit S10).
    refused = await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={"email": {"smtp_port": 465, "smtp_security": "tls"}},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "settings.email.secret_required"
    assert refused.json()["error"]["details"]["fields"] == ["smtp_password"]
    email = await _patch(
        client,
        admin,
        smtp_port=465,
        smtp_security="tls",
        smtp_password="Pa55-word-SMTP",
    )
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

    # The stored password does not leave for a server chosen afterwards
    # (audit S10): nothing is sent, nothing is saved.
    refused = await client.post(
        "/api/v1/settings/email/test",
        headers=admin,
        json={
            "to": "autre@x.fr",
            "email": {"smtp_host": "new.x.fr", "smtp_port": 2525},
        },
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "settings.email.secret_required"
    assert fake_smtp.instances == []

    # A field that does not move the password: it is used as stored.
    same = await client.post(
        "/api/v1/settings/email/test",
        headers=admin,
        json={"to": "autre@x.fr", "email": {"from_name": "Essai"}},
    )
    assert same.json()["ok"] is True
    assert fake_smtp.instances[-1].login_args == ("tiai@x.fr", "pw-stored")

    resp = await client.post(
        "/api/v1/settings/email/test",
        headers=admin,
        json={
            "to": "autre@x.fr",
            "email": {
                "smtp_host": "new.x.fr",
                "smtp_port": 2525,
                "smtp_password": "pw-new",
            },
        },
    )

    assert resp.json()["ok"] is True
    session = fake_smtp.instances[-1]
    assert (session.host, session.port) == ("new.x.fr", 2525)
    assert session.login_args == ("tiai@x.fr", "pw-new")
    assert session.sent["To"] == "autre@x.fr"
    rows = await get_all(db_session)
    assert rows["email.smtp_host"] == "old.x.fr"
    assert "email.smtp_port" not in rows
    assert secretbox.decrypt(rows["email.smtp_password"]) == "pw-stored"
    entry = (await _audit(db_session, "settings.email_test"))[-1]
    assert entry.details["unsaved"] == "smtp_host, smtp_password, smtp_port"


async def test_the_mailgun_key_does_not_follow_a_new_url(
    client, db_session, monkeypatch
):
    """Audit S10: the scenario of the report, a collector URL. The
    environment's key, which a null hands the field back to, is guarded too."""
    from app.core.config import settings as env

    monkeypatch.setattr(env, "MAILGUN_API_KEY", "key-env")
    fake_mailgun = _mailgun_answering(monkeypatch, 200)
    admin = await _admin(client, db_session)
    await _patch(
        client,
        admin,
        provider="mailgun",
        mailgun_domain="mg.x.fr",
        mailgun_api_key="key-stored",
        from_email="tiai@x.fr",
    )
    for change in (
        {"mailgun_base_url": "https://collecteur.attaquant.example"},
        {"mailgun_domain": "autre.example"},
        {
            "mailgun_base_url": "https://collecteur.attaquant.example",
            "mailgun_api_key": None,
        },
    ):
        resp = await client.post(
            "/api/v1/settings/email/test", headers=admin, json={"email": change}
        )
        assert resp.status_code == 422, (change, resp.text)
        assert resp.json()["error"]["details"]["fields"] == ["mailgun_api_key"]
        patched = await client.patch(
            "/api/v1/settings", headers=admin, json={"email": change}
        )
        assert patched.status_code == 422, (change, patched.text)
    assert fake_mailgun == []

    # The same URL written differently is not a new destination.
    ok = await client.post(
        "/api/v1/settings/email/test",
        headers=admin,
        json={"email": {"mailgun_base_url": "https://API.mailgun.net/v3/"}},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"] is True, ok.text


async def test_the_environment_secret_does_not_follow_in_two_steps(
    client, db_session, fake_smtp, monkeypatch
):
    """Audit S10, second pass: a dummy password typed with a new server, then
    the field handed back to the ``.env`` (null), must not send the
    environment's password to that server — through the test send, the
    PATCH, or a settings row written before the rule."""
    from app.core.config import settings as env
    from app.features.setting import crud as setting_crud

    monkeypatch.setattr(env, "SMTP_HOST", "smtp.corp.example")
    monkeypatch.setattr(env, "SMTP_USER", "tiai@corp.example")
    monkeypatch.setattr(env, "SMTP_PASSWORD", "ENV-SECRET-PW")
    monkeypatch.setattr(env, "EMAIL_FROM_EMAIL", "tiai@corp.example")
    admin = await _admin(client, db_session)
    await _patch(
        client,
        admin,
        provider="smtp",
        smtp_host="evil.example",
        smtp_port=25,
        smtp_security="none",
        smtp_password="dummy",
    )

    for json in (
        {"email": {"smtp_password": None}},
        {"email": {"smtp_password": None, "from_name": "Essai"}},
    ):
        tried = await client.post(
            "/api/v1/settings/email/test", headers=admin, json=json
        )
        assert tried.status_code == 422, tried.text
        assert tried.json()["error"]["details"]["fields"] == ["smtp_password"]
    handed_back = await client.patch(
        "/api/v1/settings", headers=admin, json={"email": {"smtp_password": None}}
    )
    assert handed_back.status_code == 422, handed_back.text
    assert fake_smtp.instances == []

    # A row left by an earlier version: the console's server, no password of
    # its own. The environment's password stays home.
    await setting_crud.set_value(db_session, "email.smtp_password", None, actor="x")
    await db_session.commit()
    sent = await client.post("/api/v1/settings/email/test", headers=admin, json={})
    assert sent.status_code == 200, sent.text
    assert fake_smtp.instances[-1].host == "evil.example"
    assert fake_smtp.instances[-1].login_args == ("tiai@corp.example", "")

    # Back on the environment's own server, the environment's password is
    # used again, whatever the case of the host.
    await _patch(
        client,
        admin,
        smtp_host="SMTP.corp.example",
        smtp_port=None,
        smtp_security=None,
        smtp_password=None,
    )
    again = await client.post("/api/v1/settings/email/test", headers=admin, json={})
    assert again.json()["ok"] is True, again.text
    assert fake_smtp.instances[-1].login_args == (
        "tiai@corp.example",
        "ENV-SECRET-PW",
    )


async def test_a_withheld_environment_password_is_said_on_the_page(
    client, db_session, monkeypatch
):
    """Third pass: with the console's server and the ``.env``'s account, the
    ``.env`` password is held back — and the page said « configuré » while
    every send failed on authentication."""
    from app.core.config import settings as env

    monkeypatch.setattr(env, "SMTP_HOST", "smtp.corp.example")
    monkeypatch.setattr(env, "SMTP_USER", "tiai@corp.example")
    monkeypatch.setattr(env, "SMTP_PASSWORD", "ENV-SECRET-PW")
    monkeypatch.setattr(env, "EMAIL_FROM_EMAIL", "tiai@corp.example")
    monkeypatch.setattr(env, "EMAIL_PROVIDER", "smtp")
    admin = await _admin(client, db_session)

    untouched = (await client.get("/api/v1/settings", headers=admin)).json()["email"]
    assert untouched["configured"] is True
    assert untouched["withheld"] == []

    moved = await _patch(
        client, admin, smtp_host="autre.example", smtp_password="typed-for-autre"
    )
    assert moved["withheld"] == [] and moved["configured"] is True

    # The row an earlier version could leave: the console's server, no
    # password of its own.
    from app.features.setting import crud as setting_crud

    await setting_crud.set_value(db_session, "email.smtp_password", None, actor="x")
    await db_session.commit()
    legacy = (await client.get("/api/v1/settings", headers=admin)).json()["email"]
    assert legacy["withheld"] == ["smtp_password"]
    assert legacy["configured"] is False
    assert any("mot de passe SMTP" in item for item in legacy["missing"])


async def test_an_unreadable_secret_does_not_follow_a_server_change(
    client, db_session, monkeypatch
):
    """Third pass: a console password sealed under a ``SECRET_KEY`` since
    changed reads as absent, so moving the server asked for nothing — and the
    sealed row stayed, to leave for the new server the day the key came
    back."""
    from app.core.config import settings as env

    admin = await _admin(client, db_session)
    await _patch(
        client,
        admin,
        provider="smtp",
        smtp_host="a.example",
        from_email="tiai@a.example",
        smtp_user="tiai@a.example",
        smtp_password="typed-for-a",
    )
    monkeypatch.setattr(env, "SECRET_KEY", "a-new-secret-key-after-rotation-0123")
    # The key signs the access tokens too: log in again under the new one.
    again = await client.post(
        "/api/v1/auth/login", data={"username": "admin@test.local", "password": STRONG}
    )
    admin = {"Authorization": f"Bearer {again.json()['access_token']}"}
    shown = (await client.get("/api/v1/settings", headers=admin)).json()["email"]
    assert shown["smtp_password_unreadable"] is True

    moved = await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={"email": {"smtp_host": "evil.example", "smtp_security": "none"}},
    )
    assert moved.status_code == 422, moved.text
    assert moved.json()["error"]["details"]["fields"] == ["smtp_password"]
    # Typed again, or dropped, with the move: accepted.
    await _patch(client, admin, smtp_host="b.example", smtp_password="typed-for-b")


async def test_the_environment_mailgun_key_does_not_follow_in_two_steps(
    client, db_session, monkeypatch
):
    from app.core.config import settings as env

    monkeypatch.setattr(env, "MAILGUN_API_KEY", "ENV-MAILGUN-KEY")
    monkeypatch.setattr(env, "MAILGUN_DOMAIN", "mg.corp.example")
    fake_mailgun = _mailgun_answering(monkeypatch, 200)
    admin = await _admin(client, db_session)
    await _patch(
        client,
        admin,
        provider="mailgun",
        from_email="tiai@x.fr",
        mailgun_base_url="https://collecteur.attaquant.example",
        mailgun_api_key="dummy",
    )
    tried = await client.post(
        "/api/v1/settings/email/test",
        headers=admin,
        json={"email": {"mailgun_api_key": None}},
    )
    assert tried.status_code == 422, tried.text
    assert tried.json()["error"]["details"]["fields"] == ["mailgun_api_key"]
    assert not [c for c in fake_mailgun if "url" in c]


async def test_turning_the_certificate_check_off_needs_the_password(client, db_session):
    admin = await _admin(client, db_session)
    await _patch(
        client, admin, provider="smtp", smtp_host="smtp.x.fr", smtp_password="pw"
    )
    off = await client.patch(
        "/api/v1/settings", headers=admin, json={"email": {"smtp_verify_tls": False}}
    )
    assert off.status_code == 422
    # Back on, or a change of login, moves nothing.
    await _patch(client, admin, smtp_verify_tls=False, smtp_password="pw")
    await _patch(client, admin, smtp_verify_tls=True)
    await _patch(client, admin, smtp_user="autre@x.fr")


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


# --- What the test send says, against real sockets (acceptance, 2026-11) ----------


def _local_policy(port: int, **values):
    from app.features.setting import email_policy as mail

    return mail.resolve(
        mail.StoredEmailSettings(
            values={
                "provider": "smtp",
                "smtp_host": "127.0.0.1",
                "smtp_port": port,
                "smtp_security": "none",
                "smtp_timeout_seconds": 1,
                "from_email": "tiai@lycee.local",
                **values,
            }
        )
    )


async def test_a_silent_server_is_said_not_to_answer():
    """A server that accepts the connection and never speaks: not « a fermé
    la connexion », but « n'a pas répondu dans les N s »."""
    import asyncio

    from app.features.notification import probe

    held: list[asyncio.StreamWriter] = []

    async def silent(reader, writer):
        held.append(writer)
        await asyncio.sleep(30)

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await probe.send_test(_local_policy(port), "a@lycee.local")
    finally:
        for writer in held:
            writer.close()
        server.close()
    assert result.ok is False
    assert "n'a pas répondu dans les 1 s" in result.message, result.message
    assert "fermé" not in result.message


async def test_a_server_wanting_a_login_says_so():
    """530 to MAIL FROM, with no account configured: authentication is what is
    missing, not the sender address."""
    import asyncio

    from app.features.notification import probe

    async def wants_auth(reader, writer):
        writer.write(b"220 relay ESMTP\r\n")
        await writer.drain()
        while line := await reader.readline():
            verb = line[:4].upper()
            if verb in (b"EHLO", b"HELO"):
                writer.write(b"250-relay\r\n250 AUTH PLAIN LOGIN\r\n")
            elif verb == b"MAIL":
                writer.write(b"530 5.7.0 Authentication required\r\n")
            elif verb == b"QUIT":
                writer.write(b"221 bye\r\n")
                await writer.drain()
                break
            else:
                writer.write(b"250 ok\r\n")
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(wants_auth, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await probe.send_test(_local_policy(port), "a@lycee.local")
    finally:
        server.close()
    assert result.ok is False
    assert "exige une authentification" in result.message, result.message
    assert "renseignez l'utilisateur" in result.message
    assert "Adresse d'expéditeur" not in result.message


async def _send_test_to(handler, **values):
    import asyncio

    from app.features.notification import probe

    held: list[asyncio.StreamWriter] = []

    async def handle(reader, writer):
        held.append(writer)
        await handler(reader, writer)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        return await probe.send_test(_local_policy(port, **values), "a@lycee.local")
    finally:
        for writer in held:
            writer.close()
        server.close()


async def test_a_server_wanting_starttls_points_at_the_security_mode():
    """« 530 Must issue a STARTTLS command first » — security « Aucune » on a
    587 server. The 530 was read as a missing login, and the administrator
    sent to type a user and a password the server never asked for."""

    async def wants_starttls(reader, writer):
        writer.write(b"220 relay ESMTP\r\n")
        await writer.drain()
        while line := await reader.readline():
            verb = line[:4].upper()
            if verb in (b"EHLO", b"HELO"):
                writer.write(b"250-relay\r\n250 STARTTLS\r\n")
            elif verb == b"MAIL":
                writer.write(b"530 5.7.0 Must issue a STARTTLS command first\r\n")
            elif verb == b"QUIT":
                writer.write(b"221 bye\r\n")
                await writer.drain()
                break
            else:
                writer.write(b"250 ok\r\n")
            await writer.drain()

    result = await _send_test_to(wants_starttls)
    assert result.ok is False
    assert "connexion chiffrée" in result.message, result.message
    assert "sécurité « STARTTLS »" in result.message
    assert "Must issue a STARTTLS command first" in result.message
    assert "authentification" not in result.message
    assert "utilisateur" not in result.message


async def test_a_silent_server_in_implicit_tls_is_said_not_to_answer():
    """Security « TLS implicite » on a server that accepts the connection and
    says nothing: the handshake runs out of the socket's own delay — 1 s
    here — and the message gave the 25 s of the whole test, without the
    sentence the two other modes get."""
    import asyncio

    async def silent(reader, writer):
        await asyncio.sleep(30)

    result = await _send_test_to(silent, smtp_security="tls")
    assert result.ok is False
    assert "a accepté la connexion mais n'a pas répondu" in result.message
    assert "dans les 1 s" in result.message, result.message
    assert "25 s" not in result.message
    assert "TLS sur 465" in result.message


def test_a_timeout_names_the_delay_that_ran_out():
    """A network step (the connection to a host that drops the packets)
    runs out of the socket's delay; only the whole test running out of its
    own gets the overall figure."""
    import asyncio

    from app.features.notification import probe

    policy = _local_policy(25, smtp_timeout_seconds=7)
    step = probe.describe_error(TimeoutError("timed out"), policy)
    assert step == "Le serveur 127.0.0.1:25 n'a pas répondu dans le délai imparti (7 s)"

    overall = TimeoutError()
    overall.__cause__ = asyncio.CancelledError()  # as asyncio.wait_for raises it
    assert "(25 s)" in probe.describe_error(overall, policy)


async def test_the_whole_test_running_out_says_its_own_delay(monkeypatch):
    """The real thing: a silent server whose socket delay (5 s) is longer
    than the delay of the whole test (cut to 1 s here)."""
    import asyncio

    from app.features.notification import probe

    monkeypatch.setattr(probe, "_OVERALL_TIMEOUT_SECONDS", 1)

    async def silent(reader, writer):
        await asyncio.sleep(30)

    result = await _send_test_to(silent, smtp_timeout_seconds=5)
    assert result.ok is False
    assert result.message.endswith("n'a pas répondu dans le délai imparti (1 s)")


def test_a_530_with_an_account_points_at_the_account():
    from app.features.notification import probe

    policy = _local_policy(25, smtp_user="relay@lycee.local")
    message = probe.describe_error(
        smtplib.SMTPSenderRefused(530, b"Authentication required", "t@x.fr"), policy
    )
    assert "exige une authentification" in message
    assert "vérifiez l'utilisateur" in message


# --- TLS verification of the SMTP server, against real sockets --------------------
#
# What « vérifier le certificat » checks, held by real handshakes: a relay
# behind a home-made CA — `openssl req -x509`, no key-usage extension — that
# v1.2.0 (Python 3.12) accepted must still be accepted, and neither a
# certificate for another host nor one from an unknown CA may pass.


def _private_ca(name: str):
    """A CA as `openssl req -x509` makes one: basicConstraints and nothing
    about key usage — what RFC 5280 asks of a CA and what many home-made
    ones lack."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert, key


def _server_context(folder, ca, host: str):
    """A TLS server context holding a certificate for ``host`` signed by
    ``ca`` (SAN only, like a leaf signed with a one-line extfile)."""
    import datetime
    import ssl

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    ca_cert, ca_key = ca
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), False)
        .sign(ca_key, hashes.SHA256())
    )
    pem = folder / f"{host}-{cert.serial_number}.pem"
    pem.write_bytes(
        cert.public_bytes(serialization.Encoding.PEM)
        + key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(pem)
    return context


def _trust(monkeypatch, folder, ca) -> None:
    """Make ``ca`` the container's trust store — what mounting a private CA
    and pointing ``SSL_CERT_FILE`` at it does."""
    from cryptography.hazmat.primitives import serialization

    path = folder / "ca.pem"
    path.write_bytes(ca[0].public_bytes(serialization.Encoding.PEM))
    monkeypatch.setenv("SSL_CERT_FILE", str(path))
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)


class _TlsRelay:
    """A one-thread SMTP server speaking real TLS: implicit (« tls », port
    465 style) or after STARTTLS. Counts the mails it accepted."""

    def __init__(self, context, *, starttls: bool = False) -> None:
        import threading

        self.context, self.starttls = context, starttls
        self.delivered = 0
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self) -> None:
        self.sock.close()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            try:
                conn.settimeout(5)
                self._dialogue(conn)
            except OSError:
                pass  # a refused handshake: the client went away
            finally:
                conn.close()

    def _dialogue(self, conn) -> None:
        if not self.starttls:
            conn = self.context.wrap_socket(conn, server_side=True)
        conn.sendall(b"220 relay ESMTP\r\n")
        stream = conn.makefile("rb")
        while line := stream.readline():
            verb = line[:4].upper()
            if verb == b"EHLO":
                conn.sendall(b"250-relay\r\n250 STARTTLS\r\n")
            elif verb == b"STAR":
                conn.sendall(b"220 go ahead\r\n")
                conn = self.context.wrap_socket(conn, server_side=True)
                stream = conn.makefile("rb")
            elif verb == b"DATA":
                conn.sendall(b"354 go\r\n")
                while stream.readline() not in (b".\r\n", b""):
                    pass
                self.delivered += 1
                conn.sendall(b"250 queued\r\n")
            elif verb == b"QUIT":
                conn.sendall(b"221 bye\r\n")
                return
            else:
                conn.sendall(b"250 ok\r\n")


def _relay_policy(relay: _TlsRelay, **values):
    return _local_policy(
        relay.port,
        smtp_host="localhost",
        smtp_security="starttls" if relay.starttls else "tls",
        smtp_timeout_seconds=5,
        **values,
    )


@pytest.mark.parametrize("starttls", [False, True], ids=["tls", "starttls"])
async def test_a_relay_behind_a_home_made_ca_is_still_verified_and_accepted(
    starttls, tmp_path, monkeypatch
):
    """Python 3.13 made ``ssl.create_default_context`` strict about RFC 5280
    (``VERIFY_X509_STRICT``): a CA without a key-usage extension, accepted
    under the Python 3.12 of v1.2.0, was refused after the upgrade — every
    mail of the site failing on CERTIFICATE_VERIFY_FAILED."""
    import ssl

    ca = _private_ca("AC du lycee")
    _trust(monkeypatch, tmp_path, ca)
    relay = _TlsRelay(_server_context(tmp_path, ca, "localhost"), starttls=starttls)
    try:
        # The certificate is one the strict default refuses: the test would
        # prove nothing with a CA that satisfied it.
        strict = ssl.create_default_context()
        if strict.verify_flags & ssl.VERIFY_X509_STRICT and not starttls:
            with (
                pytest.raises(ssl.SSLCertVerificationError),
                socket.create_connection(("127.0.0.1", relay.port)) as raw,
            ):
                strict.wrap_socket(raw, server_hostname="localhost")
        assert await smtp.send_email(
            "s", "t", ["a@lycee.local"], policy=_relay_policy(relay)
        )
    finally:
        relay.close()
    assert relay.delivered == 1


@pytest.mark.parametrize("starttls", [False, True], ids=["tls", "starttls"])
@pytest.mark.parametrize("wrong", ["host", "ca"])
async def test_a_certificate_for_another_host_or_ca_is_refused(
    wrong, starttls, tmp_path, monkeypatch
):
    """Relaxing the strict flag relaxes nothing else: the chain must still
    end at a trusted CA and the certificate must still name the server."""
    import ssl

    from app.features.notification import probe

    ca = _private_ca("AC du lycee")
    _trust(monkeypatch, tmp_path, ca)
    if wrong == "host":
        context = _server_context(tmp_path, ca, "autre.lycee.local")
    else:
        context = _server_context(tmp_path, _private_ca("AC inconnue"), "localhost")
    relay = _TlsRelay(context, starttls=starttls)
    policy = _relay_policy(relay)
    try:
        with pytest.raises(ssl.SSLCertVerificationError) as refused:
            await smtp.send_email("s", "t", ["a@lycee.local"], policy=policy)
        assert "Certificat du serveur" in probe.describe_error(refused.value, policy)
        assert relay.delivered == 0
        # « Vérifier le certificat » off: the administrator's own choice,
        # and the only way such a server is talked to.
        unverified = _relay_policy(relay, smtp_verify_tls=False)
        assert await smtp.send_email("s", "t", ["a@lycee.local"], policy=unverified)
    finally:
        relay.close()
    assert relay.delivered == 1


# --- A send abandoned at stop must not hold the process ---------------------------


def test_a_send_stuck_on_a_silent_server_does_not_hold_the_exit():
    """The worker's stop cancels a send that outlasts its grace. Run in the
    loop's default executor, that send was joined when the loop closed: the
    process stayed for a whole SMTP timeout more — past the ten seconds
    `docker stop` gives before it kills."""
    import subprocess
    import sys
    import time

    script = """
import asyncio, socket
from app.features.notification import smtp
from app.features.setting import email_policy as mail

silent = socket.socket()
silent.bind(("127.0.0.1", 0))
silent.listen(1)  # accepts the connection, never speaks
policy = mail.resolve(mail.StoredEmailSettings(values={
    "provider": "smtp", "smtp_host": "127.0.0.1",
    "smtp_port": silent.getsockname()[1], "smtp_security": "none",
    "smtp_timeout_seconds": 30, "from_email": "tiai@lycee.local",
}))

async def main():
    send = asyncio.create_task(smtp.send_email("s", "t", ["a@x.fr"], policy=policy))
    await asyncio.sleep(0.5)
    assert not send.done()
    send.cancel()  # what finish_background does once the grace is spent
    print("cancelled", flush=True)

asyncio.run(main())
"""
    started = time.monotonic()
    run = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert run.returncode == 0, run.stderr
    assert "cancelled" in run.stdout
    assert time.monotonic() - started < 10, "the process waited for the stuck send"
