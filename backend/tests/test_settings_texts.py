"""The French of the page Paramètres that the server writes, shared with the console.

Since the bilingual console (plan ``dev/plan-console-bilingue.md``, I2), the
console words the server's environment (a group's name, a variable's value and
description), the e-mail card's « il manque … » and the outcome of the test
e-mail itself, from the codes, raw values and parameters the server sends. Its
French must stay what the server writes beside them: an installation updated to
this version reads the same as before.

``tests/data/settings_texts_fr.json`` holds the cases: this test checks the
server still writes them, ``frontend/src/utils/serverEnvironment.spec.ts`` and
``frontend/src/utils/emailSettings.spec.ts`` that the console writes the same.
Regenerate it after a deliberate change of wording with
``python -m tests.test_settings_texts`` (run from ``backend/``), and change the
console's catalogues (``settingsEnv.ts``, ``settings.ts``) to match.
"""

import asyncio
import json
import os
import smtplib
import socket
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

FIXTURE = Path(__file__).parent / "data" / "settings_texts_fr.json"


@contextmanager
def _clean_environ() -> Iterator[None]:
    """No variable of the process's environment leaks into the cases: the
    fixture is the same on every machine."""
    from app.core.config import Settings

    names = {name.upper() for name in Settings.model_fields}
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.upper() in names}
    try:
        yield
    finally:
        os.environ.update(saved)


def _settings(**overrides: Any):
    from app.core.config import Settings

    with _clean_environ():
        return Settings(_env_file=None, ENVIRONMENT="local", **overrides)  # type: ignore[call-arg]


# Each scenario: the whole overview under these settings.
SCENARIOS: dict[str, dict[str, Any]] = {
    "defaults": {},
    "mailgun": {
        "EMAIL_PROVIDER": "mailgun",
        "MAILGUN_DOMAIN": "mg.lycee.pf",
        "MAILGUN_API_KEY": "key-0123456789",
        "MAILGUN_PROXY_URL": "http://jdupont:s3cr3t@10.0.0.1:3128",
        "EMAIL_FROM_EMAIL": "tiai@lycee.pf",
        "EMAIL_FROM_NAME": "Parc du lycée",
        "ROOM_SOURCE": "ad_ou",
        "MAINTENANCE_REMINDER_WEEKDAY": 4,
        "PACKAGE_MAX_BYTES": 1536 * 1024**2,
        "WOL_RELAY_ENABLED": True,
        "WOL_BROADCAST_ADDRESSES": "10.0.0.255, 10.0.1.255",
        "TIAI_SERVER_NAME": "tiai.lycee.pf",
        "AGENT_EXPECTED_VERSION": "1.2.0",
        "DEFAULT_LANGUAGE": "en",
    },
    "mailgun_proxy_unreadable": {
        "EMAIL_PROVIDER": "mailgun",
        "MAILGUN_PROXY_URL": "http://jdupont:123/abc@proxy:3128",
        "ROOM_SOURCE": "ad_location",
        "MAINTENANCE_REMINDER_WEEKDAY": 6,
        "PACKAGE_MAX_BYTES": 1024**2 + 512 * 1024,
        "CONSOLE_BASE_URL": "https://console.lycee.pf:8443/",
    },
    "smtp": {
        "EMAIL_PROVIDER": "smtp",
        "SMTP_HOST": "smtp.office365.com",
        "SMTP_SECURITY": "tls",
        "SMTP_PORT": 465,
        "SMTP_VERIFY_TLS": False,
        "SMTP_USER": "never-shown@lycee.pf",
        "SMTP_PASSWORD": "never-shown",
        "EMAIL_FROM_EMAIL": "tiai@lycee.pf",
        "TRUSTED_PROXIES": "172.18.0.0/24,10.9.0.0/24",
        "WOL_ALLOWED_NETWORKS": "10.4.0.0/16,10.5.0.0/16",
        "EXPOSE_OPENAPI": True,
        "RATE_LIMIT_ENABLED": False,
        "MAINTENANCE_REMINDER_WEEKDAY": 2,
        "PACKAGE_MAX_BYTES": 8 * 1024**3,
    },
    "smtp_incomplete": {
        "EMAIL_PROVIDER": "smtp",
        "MAINTENANCE_REMINDER_WEEKDAY": 1,
        "PACKAGE_MAX_BYTES": 1288490189,
    },
}

# The variable lines whose value is worded, one setting at a time.
ITEM_CASES: list[tuple[str, dict[str, Any]]] = [
    *[
        ("MAINTENANCE_REMINDER_WEEKDAY", {"MAINTENANCE_REMINDER_WEEKDAY": d})
        for d in range(7)
    ],
    *[("ROOM_SOURCE", {"ROOM_SOURCE": s}) for s in ("manual", "ad_ou", "ad_location")],
    *[
        ("PACKAGE_MAX_BYTES", {"PACKAGE_MAX_BYTES": n})
        for n in (
            1024**2,
            1024**2 + 1,
            5 * 1024**2 + 1024**2 // 4,  # 5.25: rounded half to even
            1023 * 1024**2 + 1024**2 // 2,
            1024**3 - 1,
            1024**3 + 1024**3 // 20,
            3 * 1024**3 + 1024**3 // 4,  # 3.25
            3 * 1024**3 + 3 * 1024**3 // 4,  # 3.75
        )
    ],
    *[
        ("MAILGUN_PROXY_URL", {"EMAIL_PROVIDER": "mailgun", "MAILGUN_PROXY_URL": url})
        for url in (
            "http://proxy.lycee.pf:3128",
            "https://user@proxy.example",
            "http://[fd00::1]:3128",
            "http://[::1",
            "http://pro xy:3128",
        )
    ],
    (
        "EMAIL_PROVIDER",
        {
            "EMAIL_PROVIDER": "mailgun",
            "MAILGUN_DOMAIN": "mg.x.fr",
            "MAILGUN_API_KEY": "k",
        },
    ),
    (
        "EMAIL_PROVIDER",
        {
            "EMAIL_PROVIDER": "smtp",
            "SMTP_HOST": "smtp.x.fr",
            "EMAIL_FROM_EMAIL": "a@x.fr",
        },
    ),
    ("EMAIL_PROVIDER", {"EMAIL_PROVIDER": "smtp"}),
    ("WOL_RELAY_ENABLED", {"WOL_RELAY_ENABLED": False}),
    ("WOL_RELAY_ENABLED", {"WOL_RELAY_ENABLED": True}),
]


def _environment() -> list[dict[str, Any]]:
    from app.features.setting.environment import environment_overview

    return [
        {
            "name": name,
            "settings": overrides,
            "groups": [asdict(g) for g in environment_overview(_settings(**overrides))],
        }
        for name, overrides in SCENARIOS.items()
    ]


def _environment_items() -> list[dict[str, Any]]:
    from app.features.setting.environment import environment_overview

    out = []
    for key, overrides in ITEM_CASES:
        groups = environment_overview(_settings(**overrides))
        item = next(i for g in groups for i in g.items if i.key == key)
        out.append({"settings": overrides, **asdict(item)})
    return out


def _policy(**values: Any):
    from app.features.setting import email_policy as mail

    secrets = {
        k: values.pop(k) for k in ("smtp_password", "mailgun_api_key") if k in values
    }
    return mail.resolve(
        mail.StoredEmailSettings(values=values, secrets=secrets), _settings()
    )


def _smtp(**values: Any):
    return _policy(
        provider="smtp",
        smtp_host="smtp.x.fr",
        from_email="t@x.fr",
        smtp_password="hunter2-secret",
        smtp_timeout_seconds=10,
        **values,
    )


def _mailgun():
    return _policy(
        provider="mailgun", mailgun_domain="mg.x.fr", mailgun_api_key="key-hunter2"
    )


def _http_error(status: int, **response: Any) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.mailgun.net/v3/mg.x.fr/messages")
    return httpx.HTTPStatusError(
        "error",
        request=request,
        response=httpx.Response(status, request=request, **response),
    )


def _failures() -> list[tuple[Any, BaseException]]:
    cert = ssl.SSLCertVerificationError(1, "certificate verify failed")
    cert.verify_message = "self-signed certificate"
    overall = TimeoutError()
    overall.__cause__ = asyncio.CancelledError()
    silent = smtplib.SMTPServerDisconnected("Connection unexpectedly closed: timed out")
    return [
        (
            _smtp(),
            smtplib.SMTPSenderRefused(
                530, b"5.7.0 Must issue a STARTTLS command first", "t@x.fr"
            ),
        ),
        (
            _smtp(),
            smtplib.SMTPSenderRefused(530, b"5.7.0 Authentication required", "t@x.fr"),
        ),
        (
            _smtp(smtp_user="relay@x.fr"),
            smtplib.SMTPSenderRefused(530, b"Authentication required", "t@x.fr"),
        ),
        (_smtp(), silent),
        (
            _smtp(),
            smtplib.SMTPAuthenticationError(
                535, b"5.7.8 bad credentials hunter2-secret"
            ),
        ),
        (_smtp(), smtplib.SMTPSenderRefused(553, b"not owner", "t@x.fr")),
        (
            _smtp(),
            smtplib.SMTPRecipientsRefused(
                {"a@x.fr": (550, b"no such user"), "b@x.fr": (551, "gone")}
            ),
        ),
        (_smtp(), smtplib.SMTPNotSupportedError("STARTTLS extension not supported")),
        (_smtp(), smtplib.SMTPServerDisconnected("closed")),
        (_smtp(), smtplib.SMTPDataError(554, b"rejected")),
        (_smtp(), smtplib.SMTPDataError(554, ("x" * 500).encode())),
        (_smtp(), smtplib.SMTPException("odd")),
        (_smtp(), cert),
        (_smtp(), ssl.SSLError(1, "wrong version number")),
        (_smtp(), socket.gaierror(-2, "Name or service not known")),
        (_mailgun(), _http_error(401)),
        (_mailgun(), _http_error(404)),
        (_mailgun(), _http_error(500, json={"message": " Internal failure "})),
        (_mailgun(), _http_error(502, text="<html>bad gateway</html>")),
        (_mailgun(), httpx.ConnectTimeout("timed out")),
        (_mailgun(), httpx.ConnectError("refused")),
        (_smtp(), TimeoutError("_ssl.c:1011: The handshake operation timed out")),
        (_smtp(), TimeoutError("timed out")),
        (_smtp(), overall),
        (_mailgun(), TimeoutError()),
        (_smtp(), ConnectionRefusedError(111, "Connection refused")),
        (_smtp(), OSError(101, "Network is unreachable")),
        (_mailgun(), OSError("no route")),
        (_smtp(), ValueError("hunter2-secret leaked")),
    ]


def _email_test() -> list[dict[str, Any]]:
    """What the page shows under « Envoyer un e-mail de test »: each outcome
    through ``send_test`` itself, the sender replaced by one that succeeds or
    raises — no network."""
    from app.features.notification import probe

    async def run(policy: Any, outcome: BaseException | None) -> Any:
        async def send(*args: Any, **kwargs: Any) -> bool:
            if outcome is not None:
                raise outcome
            return True

        original = probe.send_email
        probe.send_email = send  # type: ignore[assignment]
        try:
            return await probe.send_test(policy, "admin@lycee.pf")
        finally:
            probe.send_email = original  # type: ignore[assignment]

    attempts: list[tuple[Any, BaseException | None]] = [
        (_smtp(), None),
        (_mailgun(), None),
        (_policy(provider="smtp"), None),
        (_policy(provider="mailgun"), None),
        (_policy(provider="smtp", smtp_host="smtp.x.fr"), None),
        *_failures(),
    ]
    out = []
    for policy, outcome in attempts:
        result = asyncio.run(run(policy, outcome))
        out.append(
            {
                "ok": result.ok,
                "code": result.code,
                "params": result.params,
                "message": result.message,
            }
        )
    return out


def _email_missing() -> list[dict[str, Any]]:
    from app.features.setting import email_policy as mail

    return [
        {"code": code, "label": label} for code, label in mail.MISSING_LABELS.items()
    ]


def cases() -> dict[str, Any]:
    # Through JSON, as the console reads them (tuples become lists).
    return json.loads(
        json.dumps(
            {
                "environment": _environment(),
                "environment_items": _environment_items(),
                "email_test": _email_test(),
                "email_missing": _email_missing(),
            },
            ensure_ascii=False,
        )
    )


def test_the_server_still_writes_the_shared_texts():
    assert cases() == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_every_format_and_group_is_covered():
    """Each format, group and outcome the server can give has a case, so the
    console's French is checked for all of them."""
    data = cases()
    items = [i for s in data["environment"] for g in s["groups"] for i in g["items"]]
    items += data["environment_items"]
    assert {i["format"] for i in items} == {
        "plain",
        "bool",
        "list",
        "bytes",
        "weekday",
        "room_source",
        "mail_state",
        "proxy",
    }
    assert {g["code"] for g in data["environment"][0]["groups"]} == {
        "fleet",
        "maintenance",
        "usage",
        "rooms",
        "email",
        "wol",
        "console",
        "packages",
    }
    codes = {c["code"] for c in data["email_test"]}
    assert codes >= {
        "sent",
        "incomplete",
        "smtp_starttls_required",
        "smtp_auth_required",
        "smtp_silent",
        "smtp_auth_failed",
        "smtp_sender_refused",
        "smtp_recipients_refused",
        "smtp_not_supported",
        "smtp_disconnected",
        "smtp_error_response",
        "smtp_error",
        "tls_certificate_refused",
        "tls_failed",
        "smtp_host_unknown",
        "mailgun_key_refused",
        "mailgun_domain_unknown",
        "mailgun_status",
        "mailgun_timeout",
        "mailgun_unreachable",
        "smtp_handshake_silent",
        "timeout",
        "connection_refused",
        "unreachable",
        "unexpected",
    }


def test_no_secret_rides_along_in_the_raw_values_or_the_parameters():
    """The new fields are as careful as the French ones: no proxy URL, no
    password, no key — not even quoted back by a server."""
    data = cases()
    # What the server sends, not the settings each case was made with.
    sent = [
        [g for s in data["environment"] for g in s["groups"]],
        [
            {k: v for k, v in i.items() if k != "settings"}
            for i in data["environment_items"]
        ],
        data["email_test"],
    ]
    rendered = json.dumps(sent, ensure_ascii=False)
    for secret in ("s3cr3t", "123/abc", "never-shown", "hunter2", "key-0123456789"):
        assert secret not in rendered, secret


def test_every_item_says_how_it_is_worded():
    from app.features.setting.environment import environment_overview

    for group in environment_overview(_settings(EMAIL_PROVIDER="smtp")):
        assert group.code
        for item in group.items:
            if item.format == "plain":
                # Shown as it comes: the raw value and the French are the same.
                assert item.value == (
                    None if item.raw in (None, "") else str(item.raw)
                ), item.key


if __name__ == "__main__":
    data = cases()
    FIXTURE.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"{sum(len(v) for v in data.values())} cases written to {FIXTURE}")
