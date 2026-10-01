"""How mail leaves the console, as resolved right now.

The environment (``EMAIL_PROVIDER``, ``SMTP_*``, ``MAILGUN_*``…) gives the
initial value of every setting; the card « Envoi des e-mails » of the page
Paramètres can write its own, field by field, in ``app_settings`` — and a row
written there wins, exactly like the maintenance and usage settings. Field by
field rather than all or nothing: an administrator who only types the SMTP
password the ``.env`` left out must not have to retype the host as well.

The two secrets (SMTP password, Mailgun API key) are stored encrypted
(``app.core.secretbox``). One the server can no longer decrypt — ``SECRET_KEY``
changed since it was typed — is treated as absent: the environment's value
applies, and the page says « à ressaisir ».

Not here: the Mailgun proxy and timeout. They describe the server's network,
not the mail account, and stay in the environment.

Freshness. Every send resolves the policy from the database at the moment it
sends (``email_policy``), so a change made in the console reaches the worker on
its next tick, without a restart. One reader cannot await: ``queue_email``,
which the password-reset and check-assignment paths call synchronously in the
middle of their transaction. It reads the *last resolution made in this
process* (``current_policy``), kept fresh by every async resolution — the
settings routes (the only writer), the heartbeat's threat alert, the digest,
the drain — and by one load when the API starts. The stack runs a single API
process (``entrypoint.sh``), the same assumption the rate limiter makes; with
several, a change made through one would reach the others' queueing guard at
their next resolution.
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import secretbox
from app.core.config import Settings
from app.core.config import settings as env
from app.features.setting import crud

Provider = Literal["mailgun", "smtp"]
Security = Literal["starttls", "tls", "none"]
PROVIDERS: tuple[Provider, ...] = ("mailgun", "smtp")
SECURITIES: tuple[Security, ...] = ("starttls", "tls", "none")

# Bounds shared by the API's validation and the reading of stored rows: a row
# out of range (written by hand, or by an older version) is ignored, not
# trusted — the environment's value applies instead.
PORT_MIN, PORT_MAX = 1, 65535
TIMEOUT_MIN, TIMEOUT_MAX = 1, 120

# The console's fields, by API name, and the ``app_settings`` key each is
# stored under.
PLAIN_KEYS: dict[str, str] = {
    "provider": "email.provider",
    "from_email": "email.from_email",
    "from_name": "email.from_name",
    "smtp_host": "email.smtp_host",
    "smtp_port": "email.smtp_port",
    "smtp_security": "email.smtp_security",
    "smtp_user": "email.smtp_user",
    "smtp_verify_tls": "email.smtp_verify_tls",
    "smtp_timeout_seconds": "email.smtp_timeout_seconds",
    "mailgun_domain": "email.mailgun_domain",
    "mailgun_base_url": "email.mailgun_base_url",
}
# Stored as a Fernet token, never in clear, and never sent back by the API.
SECRET_KEYS: dict[str, str] = {
    "smtp_password": "email.smtp_password",
    "mailgun_api_key": "email.mailgun_api_key",
}
FIELDS = frozenset(PLAIN_KEYS) | frozenset(SECRET_KEYS)


def _is_int(value: Any, low: int, high: int) -> bool:
    # ``bool`` is an ``int`` to Python; a stored true is not a port.
    return (
        isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    )


def _valid(name: str, value: Any) -> bool:
    """Whether a stored value is one this field can hold."""
    if name == "provider":
        return value in PROVIDERS
    if name == "smtp_security":
        return value in SECURITIES
    if name == "smtp_port":
        return _is_int(value, PORT_MIN, PORT_MAX)
    if name == "smtp_timeout_seconds":
        return _is_int(value, TIMEOUT_MIN, TIMEOUT_MAX)
    if name == "smtp_verify_tls":
        return isinstance(value, bool)
    return isinstance(value, str) and bool(value)


@dataclass(frozen=True)
class StoredEmailSettings:
    """What the console holds: the fields it has written (by API name), the
    secrets it could decrypt, and the ones it could not."""

    values: Mapping[str, Any] = field(default_factory=dict)
    secrets: Mapping[str, str] = field(default_factory=dict, repr=False)
    unreadable: frozenset[str] = frozenset()

    def merged(self, changes: Mapping[str, Any]) -> "StoredEmailSettings":
        """These settings with ``changes`` applied as a PATCH would apply
        them — ``None`` hands a field back to the environment — without
        writing anything: what « Envoyer un e-mail de test » sends with
        before the form is saved."""
        values = dict(self.values)
        secrets = dict(self.secrets)
        unreadable = set(self.unreadable)
        for name, value in changes.items():
            target: dict[str, Any] = secrets if name in SECRET_KEYS else values
            unreadable.discard(name)
            if value is None:
                target.pop(name, None)
            else:
                target[name] = value
        return StoredEmailSettings(values, secrets, frozenset(unreadable))


def stored_from(values: Mapping[str, Any]) -> StoredEmailSettings:
    """The console's e-mail settings out of the ``app_settings`` rows."""
    plain = {
        name: values[key]
        for name, key in PLAIN_KEYS.items()
        if _valid(name, values.get(key))
    }
    secrets: dict[str, str] = {}
    unreadable: set[str] = set()
    for name, key in SECRET_KEYS.items():
        token = values.get(key)
        if not isinstance(token, str) or not token:
            continue
        clear = secretbox.decrypt(token)
        if clear is None:
            unreadable.add(name)
        else:
            secrets[name] = clear
    return StoredEmailSettings(plain, secrets, frozenset(unreadable))


@dataclass(frozen=True)
class EmailPolicy:
    """Everything a send needs, resolved: the console's value where it wrote
    one, the environment's otherwise. Secrets are kept out of ``repr`` so a
    policy that ends up in a log line does not take them along."""

    provider: Provider
    from_email: str | None
    from_name: str
    smtp_host: str | None
    smtp_port: int
    smtp_security: Security
    smtp_user: str | None
    smtp_password: str | None = field(repr=False)
    smtp_verify_tls: bool
    smtp_timeout_seconds: int
    mailgun_domain: str | None
    mailgun_api_key: str | None = field(repr=False)
    mailgun_base_url: str
    # Environment only (see the module docstring), carried here so that a
    # test send can bound it like the SMTP one.
    mailgun_timeout_seconds: int

    @property
    def smtp_configured(self) -> bool:
        """A host and a sender: an SMTP mail with no From is refused by most
        relays. Credentials are optional (a LAN relay trusts its sources)."""
        return bool(self.smtp_host and self.from_email)

    @property
    def mailgun_configured(self) -> bool:
        return bool(self.mailgun_domain and self.mailgun_api_key)

    @property
    def enabled(self) -> bool:
        """Whether the chosen provider has what it needs — configuring the
        other one does not count."""
        if self.provider == "smtp":
            return self.smtp_configured
        return self.mailgun_configured

    def missing(self) -> list[str]:
        """What the chosen provider still lacks, in the page's words."""
        if self.provider == "smtp":
            wanted = [
                (self.smtp_host, "le serveur SMTP"),
                (self.from_email, "l'adresse d'expéditeur"),
            ]
        else:
            wanted = [
                (self.mailgun_domain, "le domaine Mailgun"),
                (self.mailgun_api_key, "la clé API Mailgun"),
            ]
        return [label for value, label in wanted if not value]

    def bounded(self, seconds: int) -> "EmailPolicy":
        """The same policy with both providers' timeouts capped at ``seconds``."""
        return dataclasses.replace(
            self,
            smtp_timeout_seconds=min(self.smtp_timeout_seconds, seconds),
            mailgun_timeout_seconds=min(self.mailgun_timeout_seconds, seconds),
        )


def resolve(stored: StoredEmailSettings, environment: Settings = env) -> EmailPolicy:
    """The console's values over the environment's, field by field.

    The environment's sender keeps its own fallbacks (``MAILGUN_FROM_*``, then
    the project name), so a ``.env`` written before SMTP existed still
    resolves to the address it always did.
    """
    v = stored.values
    s = stored.secrets
    return EmailPolicy(
        provider=cast(Provider, v.get("provider", environment.EMAIL_PROVIDER)),
        from_email=v.get("from_email", environment.email_from_email),
        from_name=v.get("from_name", environment.email_from_name),
        smtp_host=v.get("smtp_host", environment.SMTP_HOST),
        smtp_port=v.get("smtp_port", environment.SMTP_PORT),
        smtp_security=cast(Security, v.get("smtp_security", environment.SMTP_SECURITY)),
        smtp_user=v.get("smtp_user", environment.SMTP_USER),
        smtp_password=s.get("smtp_password", environment.SMTP_PASSWORD),
        smtp_verify_tls=v.get("smtp_verify_tls", environment.SMTP_VERIFY_TLS),
        smtp_timeout_seconds=v.get(
            "smtp_timeout_seconds", environment.SMTP_TIMEOUT_SECONDS
        ),
        mailgun_domain=v.get("mailgun_domain", environment.MAILGUN_DOMAIN),
        mailgun_api_key=s.get("mailgun_api_key", environment.MAILGUN_API_KEY),
        mailgun_base_url=v.get("mailgun_base_url", environment.MAILGUN_API_BASE_URL),
        mailgun_timeout_seconds=environment.MAILGUN_TIMEOUT_SECONDS,
    )


# --- The process's last resolution ---------------------------------------------

_EMPTY = StoredEmailSettings()
_last: StoredEmailSettings | None = None


def remember(stored: StoredEmailSettings) -> None:
    global _last
    _last = stored


def forget() -> None:
    """Drop the last resolution (tests: each starts from an empty table)."""
    global _last
    _last = None


def current_policy() -> EmailPolicy:
    """The policy as this process last read it, for the one synchronous
    reader (``queue_email``). What is kept is the console's rows, not the
    resolved policy: the environment is applied at each call."""
    return resolve(_last or _EMPTY)


async def load_stored(
    session: AsyncSession, values: Mapping[str, Any] | None = None
) -> StoredEmailSettings:
    """Read the console's e-mail settings, and remember them for
    ``current_policy``. ``values`` is the table already read, for a caller
    that needs it for something else too."""
    if values is None:
        values = await crud.get_all(session)
    stored = stored_from(values)
    remember(stored)
    return stored


async def email_policy(session: AsyncSession) -> EmailPolicy:
    """The policy as it stands in the database now — what every send uses."""
    return resolve(await load_stored(session))


# --- Writing ------------------------------------------------------------------


async def write(
    session: AsyncSession, changes: Mapping[str, Any], *, actor: str
) -> dict[str, str | None]:
    """Write the console's e-mail fields a patch carries. Does not commit.

    ``None`` stores a null row, which hands the field back to the
    environment — the same convention as the maintenance owner. A secret is
    encrypted before it reaches the session, so its clear value is never part
    of a flush, a log of the SQL, or a row.

    Returns what the audit line should say: the new value of a plain field,
    and only « modifié » or « effacé » for a secret.
    """
    details: dict[str, str | None] = {}
    for name in sorted(changes):
        value = changes[name]
        if name in SECRET_KEYS:
            await crud.set_value(
                session,
                SECRET_KEYS[name],
                None if value is None else secretbox.encrypt(value),
                actor=actor,
            )
            details[f"email.{name}"] = "effacé" if value is None else "modifié"
        elif name in PLAIN_KEYS:
            await crud.set_value(session, PLAIN_KEYS[name], value, actor=actor)
            details[f"email.{name}"] = None if value is None else str(value)
        else:  # pragma: no cover - the API model admits no other field
            raise ValueError(f"unknown e-mail setting {name!r}")
    return details
