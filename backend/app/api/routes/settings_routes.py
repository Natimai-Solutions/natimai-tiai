"""Console settings: the parc-wide maintenance defaults, the usage thresholds,
the parc thresholds, the mail schedule and how mail leaves — editable without
a restart. ``settings:read`` to see them, ``settings:write`` to change them —
the administrators hold both implicitly; nobody else does by default.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.api.fields import Email
from app.core import ratelimit
from app.core.config import settings as env
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.machine import crud as machine_crud
from app.features.notification import probe
from app.features.setting import crud
from app.features.setting import email_policy as mail
from app.features.setting.environment import environment_overview
from app.features.user.models import User
from app.features.user.permissions import Action, Resource

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(require_permission(Resource.SETTINGS, Action.READ))],
)
_WRITE = Depends(require_permission(Resource.SETTINGS, Action.WRITE))


class UserRef(BaseModel):
    id: uuid.UUID
    name: str


class EnvItemOut(BaseModel):
    """One variable of the server's environment, as the page prints it."""

    key: str
    # None = not set (the page shows a dash); otherwise already rendered —
    # booleans in words, lists joined — so every client prints the same thing.
    value: str | None
    description: str


class EnvGroupOut(BaseModel):
    label: str
    items: list[EnvItemOut]


class EmailEnvOut(BaseModel):
    """What the environment says for each e-mail field, for the page to show
    as « valeur du serveur ». Never a secret, nor the SMTP account name (the
    environment overview hides it too): only whether one is set."""

    provider: str
    from_email: str | None
    from_name: str
    smtp_host: str | None
    smtp_port: int
    smtp_security: str
    smtp_user_set: bool
    smtp_password_set: bool
    smtp_verify_tls: bool
    smtp_timeout_seconds: int
    mailgun_domain: str | None
    mailgun_api_key_set: bool
    mailgun_base_url: str
    # Whether the environment alone would send mail.
    configured: bool


class EmailSettingsOut(BaseModel):
    """The card « Envoi des e-mails ».

    Each field is what the *console* stored — null where it stored nothing
    and the environment's value applies (``env``). The account name is shown
    back: the administrator typed it on this page and needs to see what is
    there to correct it. The two secrets never are: only whether one is
    stored, and whether it is stored but unreadable — encrypted under a
    ``SECRET_KEY`` that has changed since, to be typed again.
    """

    provider: Literal["mailgun", "smtp"] | None
    from_email: str | None
    from_name: str | None
    smtp_host: str | None
    smtp_port: int | None
    smtp_security: Literal["starttls", "tls", "none"] | None
    smtp_user: str | None
    smtp_verify_tls: bool | None
    smtp_timeout_seconds: int | None
    mailgun_domain: str | None
    mailgun_base_url: str | None
    smtp_password_set: bool
    smtp_password_unreadable: bool
    mailgun_api_key_set: bool
    mailgun_api_key_unreadable: bool
    # The policy as it resolves now: the provider in use, whether mail
    # leaves at all, and if not what is missing (in the page's words).
    effective_provider: Literal["mailgun", "smtp"]
    configured: bool
    missing: list[str]
    env: EmailEnvOut


class SettingsOut(BaseModel):
    maintenance_default_cycle_days: int
    maintenance_default_owner: UserRef | None
    maintenance_due_soon_days: int
    # What the environment says, for the page to show where a value comes
    # from before the console ever wrote one.
    env_default_cycle_days: int
    env_due_soon_days: int
    # Usage statistics: the window and the two thresholds, as resolved, and
    # what the environment says for each.
    usage_window_days: int
    usage_low_hours: int
    usage_high_hours: int
    env_usage_window_days: int
    env_usage_low_hours: int
    env_usage_high_hours: int
    # Parc thresholds, as resolved, and the environment's value for each.
    signature_max_age_days: int
    inactive_after_days: int
    low_disk_free_percent: int
    hardware_aging_years: int
    # None = automatic: the highest version the parc reports.
    agent_expected_version: str | None
    command_default_ttl_minutes: int
    env_signature_max_age_days: int
    env_inactive_after_days: int
    env_low_disk_free_percent: int
    env_hardware_aging_years: int
    env_agent_expected_version: str | None
    env_command_default_ttl_minutes: int
    # When the worker's mails go out, and the environment's values.
    digest_hour_utc: int
    maintenance_reminder_weekday: int
    env_digest_hour_utc: int
    env_maintenance_reminder_weekday: int
    room_source: str
    # How mail leaves the console: the console's values, the environment's.
    email: EmailSettingsOut
    # The rest of the environment an administrator may want to check without
    # a shell on the server — thresholds, mail, wake-on-LAN — read-only and
    # never a secret (``app.features.setting.environment``).
    environment: list[EnvGroupOut]
    updated_at: datetime | None


# An agent version as the release workflow stamps it ("1.0.2", "v1.0.2",
# "1.1.0-rc.1"), or "" for automatic. Strict on purpose: a reference that no
# agent can ever report would flag the whole parc as behind.
AGENT_VERSION_PATTERN = r"^(|v?\d+(\.\d+){0,3}([-+][0-9A-Za-z.\-]+)?)$"


# A host name or address, as typed: no scheme, no path, no space.
_HOST = r"^[A-Za-z0-9.\-\[\]:]+$"


class EmailSettingsIn(BaseModel):
    """The e-mail fields of a patch, or the unsaved form of a test send.

    Absent = unchanged. Null = forget the console's value, the environment's
    applies again. A text field sent empty counts as null — the form's way of
    saying « reprendre la valeur du serveur ». A secret is replaced by any
    other string and is never stored in clear (``email_policy.write``); an
    empty secret is refused rather than read as « effacer », so a form that
    sends an untouched password box cannot wipe the stored one by accident.
    """

    provider: Literal["mailgun", "smtp"] | None = None
    from_email: Email | None = None
    from_name: str | None = Field(default=None, max_length=100)
    smtp_host: str | None = Field(default=None, max_length=255, pattern=_HOST)
    smtp_port: int | None = Field(default=None, ge=mail.PORT_MIN, le=mail.PORT_MAX)
    smtp_security: Literal["starttls", "tls", "none"] | None = None
    smtp_user: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = Field(default=None, min_length=1, max_length=1024)
    smtp_verify_tls: bool | None = None
    smtp_timeout_seconds: int | None = Field(
        default=None, ge=mail.TIMEOUT_MIN, le=mail.TIMEOUT_MAX
    )
    mailgun_domain: str | None = Field(default=None, max_length=255, pattern=_HOST)
    mailgun_api_key: str | None = Field(default=None, min_length=1, max_length=1024)
    mailgun_base_url: str | None = Field(
        default=None, max_length=255, pattern=r"^https?://[^\s/]+(/\S*)?$"
    )

    @field_validator(
        "from_email",
        "from_name",
        "smtp_host",
        "smtp_user",
        "mailgun_domain",
        "mailgun_base_url",
        mode="before",
    )
    @classmethod
    def _blank_is_null(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    def changes(self) -> dict[str, Any]:
        """The fields the client sent, with the value it sent."""
        return {name: getattr(self, name) for name in self.model_fields_set}


class SettingsUpdate(BaseModel):
    """Partial: only the supplied fields are written. ``owner_id`` set to
    null clears the default owner."""

    maintenance_default_cycle_days: int | None = Field(default=None, ge=0, le=3650)
    maintenance_default_owner_id: uuid.UUID | None = None
    maintenance_due_soon_days: int | None = Field(default=None, ge=0, le=365)
    # The usage window, and the two thresholds in hours. Bounded each on its
    # own here; how they relate (low below high, high reachable within the
    # window) is checked on the values once merged with what is stored.
    usage_window_days: int | None = Field(default=None, ge=1, le=90)
    usage_low_hours: int | None = Field(default=None, ge=0, le=24 * 90)
    usage_high_hours: int | None = Field(default=None, ge=1, le=24 * 90)
    # Parc thresholds. Same bounds as the environment variables they replace,
    # where those have one; the others are bounded here so a typo cannot make
    # every poste « périmé » or none ever « inactif ».
    signature_max_age_days: int | None = Field(default=None, ge=0, le=365)
    inactive_after_days: int | None = Field(default=None, ge=1, le=3650)
    low_disk_free_percent: int | None = Field(default=None, ge=1, le=99)
    hardware_aging_years: int | None = Field(default=None, ge=1, le=30)
    # "" = automatic (the highest version on the parc), which a version pinned
    # in the environment does not override; null = back to the environment.
    agent_expected_version: str | None = Field(
        default=None, max_length=64, pattern=AGENT_VERSION_PATTERN
    )
    command_default_ttl_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 30)
    # The mail schedule, read by the worker on every tick.
    digest_hour_utc: int | None = Field(default=None, ge=0, le=23)
    maintenance_reminder_weekday: int | None = Field(default=None, ge=0, le=6)

    # How mail leaves: saved by its own card, so its fields arrive together.
    email: EmailSettingsIn | None = None


def _email_out(stored: mail.StoredEmailSettings) -> EmailSettingsOut:
    policy = mail.resolve(stored)
    from_env = mail.resolve(mail.StoredEmailSettings())
    v = stored.values
    return EmailSettingsOut(
        provider=v.get("provider"),
        from_email=v.get("from_email"),
        from_name=v.get("from_name"),
        smtp_host=v.get("smtp_host"),
        smtp_port=v.get("smtp_port"),
        smtp_security=v.get("smtp_security"),
        smtp_user=v.get("smtp_user"),
        smtp_verify_tls=v.get("smtp_verify_tls"),
        smtp_timeout_seconds=v.get("smtp_timeout_seconds"),
        mailgun_domain=v.get("mailgun_domain"),
        mailgun_base_url=v.get("mailgun_base_url"),
        smtp_password_set="smtp_password" in stored.secrets,
        smtp_password_unreadable="smtp_password" in stored.unreadable,
        mailgun_api_key_set="mailgun_api_key" in stored.secrets,
        mailgun_api_key_unreadable="mailgun_api_key" in stored.unreadable,
        effective_provider=policy.provider,
        configured=policy.enabled,
        missing=policy.missing(),
        env=EmailEnvOut(
            provider=from_env.provider,
            from_email=from_env.from_email,
            from_name=from_env.from_name,
            smtp_host=from_env.smtp_host,
            smtp_port=from_env.smtp_port,
            smtp_security=from_env.smtp_security,
            smtp_user_set=bool(from_env.smtp_user),
            smtp_password_set=bool(from_env.smtp_password),
            smtp_verify_tls=from_env.smtp_verify_tls,
            smtp_timeout_seconds=from_env.smtp_timeout_seconds,
            mailgun_domain=from_env.mailgun_domain,
            mailgun_api_key_set=bool(from_env.mailgun_api_key),
            mailgun_base_url=from_env.mailgun_base_url,
            configured=from_env.enabled,
        ),
    )


async def _out(session: SessionDep) -> SettingsOut:
    from sqlmodel import col, func, select

    from app.features.setting.models import AppSetting

    values = await crud.get_all(session)
    policy = await crud.maintenance_policy(session, values)
    usage = await crud.usage_policy(session, values)
    fleet = await crud.fleet_policy(session, values)
    schedule = await crud.schedule_policy(session, values)
    # Also refreshes what this process's ``queue_email`` reads: after a
    # patch, the new mail settings apply to the very next queued mail.
    stored = await mail.load_stored(session, values)
    owner = await session.get(User, policy.owner_id) if policy.owner_id else None
    latest = await session.exec(select(func.max(col(AppSetting.updated_at))))
    updated: datetime | None = latest.one()
    return SettingsOut(
        maintenance_default_cycle_days=policy.cycle_days,
        maintenance_default_owner=(
            UserRef(id=owner.id, name=owner.full_name or owner.email) if owner else None
        ),
        maintenance_due_soon_days=policy.due_soon_days,
        env_default_cycle_days=env.MAINTENANCE_DEFAULT_CYCLE_DAYS,
        env_due_soon_days=env.MAINTENANCE_DUE_SOON_DAYS,
        usage_window_days=usage.window_days,
        usage_low_hours=usage.low_hours,
        usage_high_hours=usage.high_hours,
        env_usage_window_days=env.USAGE_WINDOW_DAYS,
        env_usage_low_hours=env.USAGE_LOW_HOURS,
        env_usage_high_hours=env.USAGE_HIGH_HOURS,
        signature_max_age_days=fleet.signature_max_age_days,
        inactive_after_days=fleet.inactive_after_days,
        low_disk_free_percent=fleet.low_disk_free_percent,
        hardware_aging_years=fleet.hardware_aging_years,
        agent_expected_version=fleet.agent_expected_version,
        command_default_ttl_minutes=fleet.command_default_ttl_minutes,
        env_signature_max_age_days=env.SIGNATURE_MAX_AGE_DAYS,
        env_inactive_after_days=env.INACTIVE_AFTER_DAYS,
        env_low_disk_free_percent=env.LOW_DISK_FREE_PERCENT,
        env_hardware_aging_years=env.HARDWARE_AGING_YEARS,
        env_agent_expected_version=env.AGENT_EXPECTED_VERSION or None,
        env_command_default_ttl_minutes=env.COMMAND_DEFAULT_TTL_MINUTES,
        digest_hour_utc=schedule.digest_hour_utc,
        maintenance_reminder_weekday=schedule.reminder_weekday,
        env_digest_hour_utc=env.DIGEST_HOUR_UTC,
        env_maintenance_reminder_weekday=env.MAINTENANCE_REMINDER_WEEKDAY,
        room_source=env.ROOM_SOURCE,
        email=_email_out(stored),
        environment=[
            EnvGroupOut(
                label=group.label,
                items=[
                    EnvItemOut(key=i.key, value=i.value, description=i.description)
                    for i in group.items
                ],
            )
            for group in environment_overview(env)
        ],
        updated_at=updated,
    )


_USAGE_KEYS = {
    "usage_window_days": crud.KEY_USAGE_WINDOW,
    "usage_low_hours": crud.KEY_USAGE_LOW,
    "usage_high_hours": crud.KEY_USAGE_HIGH,
}


async def _write_usage(
    session: SessionDep, payload: SettingsUpdate, *, actor: str
) -> None:
    """Write the usage settings a patch carries, once they hold together.

    Like the maintenance fields, an explicit null clears the stored value and
    hands the setting back to the environment. The check runs on the values
    as they will stand — the patch merged over what is stored, the
    environment behind both — since a patch may carry one threshold and leave
    the other: raising « peu utilisé » to 40 h against a stored 30 h for
    « toujours allumé » must be refused as surely as sending both. Refused
    before anything is written, so a bad patch changes nothing.
    """
    sent = payload.model_fields_set & _USAGE_KEYS.keys()
    if not sent:
        return
    current = await crud.usage_policy(session)

    def resolved(field: str, stored: int, default: int) -> int:
        if field not in sent:
            return stored
        value: int | None = getattr(payload, field)
        return default if value is None else value

    window = resolved("usage_window_days", current.window_days, env.USAGE_WINDOW_DAYS)
    low = resolved("usage_low_hours", current.low_hours, env.USAGE_LOW_HOURS)
    high = resolved("usage_high_hours", current.high_hours, env.USAGE_HIGH_HOURS)
    if low >= high:
        raise AppError(
            code=ErrorCode.REQUEST_VALIDATION_ERROR,
            status_code=422,
            message="usage_low_hours must be below usage_high_hours",
            details={"usage_low_hours": low, "usage_high_hours": high},
        )
    if high > 24 * window:
        # A threshold no poste can reach is not a setting: 200 h in a week
        # of 168 would leave the « toujours allumé » card empty forever.
        raise AppError(
            code=ErrorCode.REQUEST_VALIDATION_ERROR,
            status_code=422,
            message="usage_high_hours exceeds the hours in the window",
            details={"usage_high_hours": high, "usage_window_days": window},
        )
    for field in sorted(sent):
        await crud.set_value(
            session, _USAGE_KEYS[field], getattr(payload, field), actor=actor
        )


# Fields written as they come: each one is bounded on its own (above), and
# none depends on another. An explicit null clears the row and hands the
# setting back to the environment, like the maintenance fields.
_SIMPLE_KEYS = {
    "signature_max_age_days": crud.KEY_SIGNATURE_MAX_AGE,
    "inactive_after_days": crud.KEY_INACTIVE_AFTER,
    "low_disk_free_percent": crud.KEY_LOW_DISK,
    "hardware_aging_years": crud.KEY_HARDWARE_AGING,
    "agent_expected_version": crud.KEY_AGENT_VERSION,
    "command_default_ttl_minutes": crud.KEY_COMMAND_TTL,
    "digest_hour_utc": crud.KEY_DIGEST_HOUR,
    "maintenance_reminder_weekday": crud.KEY_REMINDER_WEEKDAY,
}


async def _write_simple(
    session: SessionDep, payload: SettingsUpdate, *, actor: str
) -> None:
    """Write the independent settings a patch carries.

    A new signature age threshold is applied to the whole parc in the same
    transaction (``recompute_up_to_date``): the « à jour » flag is stored per
    machine, and a poste that is off would otherwise keep the old verdict
    until it next reports — the list, the dashboard and the digest disagreeing
    for as long.
    """
    sent = payload.model_fields_set & _SIMPLE_KEYS.keys()
    if not sent:
        return
    before = (await crud.fleet_policy(session)).signature_max_age_days
    for field in sorted(sent):
        value = getattr(payload, field)
        if field == "agent_expected_version" and value is not None:
            value = value.strip()
        await crud.set_value(session, _SIMPLE_KEYS[field], value, actor=actor)
    if "signature_max_age_days" in sent:
        await session.flush()
        after = (await crud.fleet_policy(session)).signature_max_age_days
        if after != before:
            await machine_crud.recompute_up_to_date(session, max_age_days=after)


@router.get("", response_model=SettingsOut)
async def get_settings(session: SessionDep) -> SettingsOut:
    return await _out(session)


@router.patch("", response_model=SettingsOut, dependencies=[_WRITE])
async def update_settings(
    payload: SettingsUpdate, session: SessionDep, current: CurrentUser
) -> SettingsOut:
    fields = payload.model_dump(exclude_unset=True, exclude={"email"})
    await _write_usage(session, payload, actor=current.email)
    await _write_simple(session, payload, actor=current.email)
    if "maintenance_default_cycle_days" in fields:
        await crud.set_value(
            session,
            crud.KEY_CYCLE,
            fields["maintenance_default_cycle_days"],
            actor=current.email,
        )
    if "maintenance_due_soon_days" in fields:
        await crud.set_value(
            session,
            crud.KEY_DUE_SOON,
            fields["maintenance_due_soon_days"],
            actor=current.email,
        )
    if "maintenance_default_owner_id" in fields:
        owner_id = fields["maintenance_default_owner_id"]
        if owner_id is not None:
            owner = await session.get(User, owner_id)
            if owner is None or not owner.is_active:
                raise AppError(
                    code=ErrorCode.USER_NOT_FOUND,
                    status_code=404,
                    message="User not found",
                )
        await crud.set_value(
            session,
            crud.KEY_OWNER,
            str(owner_id) if owner_id else None,
            actor=current.email,
        )
    details: dict[str, str | None] = {
        k: (str(v) if v is not None else None) for k, v in fields.items()
    }
    if payload.email is not None:
        # The audit line names each e-mail field changed, and for a secret
        # only that it was — never the value, which would otherwise sit in
        # clear in a table every auditor can read.
        details |= await mail.write(
            session, payload.email.changes(), actor=current.email
        )
    audit.record(
        session,
        actor=current.email,
        action="settings.update",
        resource_type="settings",
        resource_id="",
        details=details,
    )
    await session.commit()
    return await _out(session)


# --- Test send ----------------------------------------------------------------


class EmailTestIn(BaseModel):
    """A test send. ``to`` defaults to the caller's own address. ``email``
    carries the card's unsaved values, applied over what is stored exactly as
    a patch would apply them — so a server can be tried before it is saved,
    and a stored password need not be typed again to try a new port."""

    to: Email | None = None
    email: EmailSettingsIn | None = None


class EmailTestOut(BaseModel):
    ok: bool
    # Readable as is: what went out, or what to fix.
    message: str


# Each accepted call sends a real mail, to an address the caller chooses:
# the budget of a person trying settings, not of a script.
email_test_limiter = ratelimit.RateLimiter(max_attempts=10, window_seconds=300)


@router.post(
    "/email/test",
    response_model=EmailTestOut,
    dependencies=[
        _WRITE,
        Depends(ratelimit.rate_limit(email_test_limiter, "settings.email_test")),
    ],
)
async def send_test_email(
    payload: EmailTestIn, session: SessionDep, current: CurrentUser
) -> EmailTestOut:
    """Send one mail now, outside the outbox, and say how it went.

    A failed send is a 200 with ``ok: false``: the request itself went
    fine, and the page shows the message under the button.
    """
    stored = await mail.load_stored(session)
    unsaved = payload.email.changes() if payload.email is not None else {}
    policy = mail.resolve(stored.merged(unsaved))
    to = payload.to or current.email
    result = await probe.send_test(policy, to)
    audit.record(
        session,
        actor=current.email,
        action="settings.email_test",
        resource_type="settings",
        resource_id="",
        details={
            "to": to,
            "provider": policy.provider,
            "ok": "oui" if result.ok else "non",
            # Which fields were tried unsaved — names only, never values.
            "unsaved": ", ".join(sorted(unsaved)) or None,
            "message": result.message,
        },
    )
    await session.commit()
    return EmailTestOut(ok=result.ok, message=result.message)
