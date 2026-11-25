"""Console settings: the parc-wide maintenance defaults, the usage thresholds,
the parc thresholds, the mail schedule and how mail leaves — editable without
a restart. ``settings:read`` to see them, ``settings:write`` to change them —
the administrators hold both implicitly; nobody else does by default.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.api.fields import Email
from app.core import ratelimit
from app.core.config import settings as env
from app.core.errors import AppError, ErrorCode
from app.features.alert.models import ALL_RULES, AlertRule
from app.features.approval import reach as approval_reach
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.machine import crud as machine_crud
from app.features.maintenance.reach import owner_reach
from app.features.notification import probe
from app.features.report import crud as report_crud
from app.features.schedule import windows
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
    # In French, like the description.
    value: str | None
    description: str
    # For a console that words the line in its reader's language (plan
    # ``dev/plan-console-bilingue.md``, I2): the value as the environment
    # holds it — never a secret —, how ``value`` words it, and the variable
    # parts of that wording (``app.features.setting.environment.EnvItem``).
    raw: Any = None
    format: str = "plain"
    params: dict[str, Any] = Field(default_factory=dict)


class EnvGroupOut(BaseModel):
    # Stable: « fleet », « maintenance », « usage », « rooms », « email »,
    # « wol », « console », « packages ». The label is its French name.
    code: str
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
    # The same, as codes, in the same order (``email_policy.MISSING_LABELS``,
    # and ``smtp_password_retype``): for a console in another language.
    missing_codes: list[str] = Field(default_factory=list)
    # The environment's secrets not sent because the console points at
    # another server than the environment's ("smtp_password",
    # "mailgun_api_key"): to be typed in the console.
    withheld: list[str]
    env: EmailEnvOut


class SettingsOut(BaseModel):
    maintenance_default_cycle_days: int
    maintenance_default_owner: UserRef | None
    # The stored default owner when it no longer resolves (deactivated,
    # rights or scope lost): the card names it rather than showing an empty
    # field, which saved as « no default owner » (audit item 3).
    maintenance_default_owner_unavailable: UserRef | None = None
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
    # Alerts: the catalogue, the rules turned on, their thresholds, the
    # « logiciels interdits » list, the rules that open a verification.
    alert_rules: list[str] = Field(default_factory=list)
    alert_enabled_rules: list[str] = Field(default_factory=list)
    alert_reboot_pending_days: int = 7
    alert_warranty_days: int = 30
    env_alert_warranty_days: int = 30
    alert_unencrypted_scope: str = "laptops"
    alert_forbidden_software: list[str] = Field(default_factory=list)
    alert_auto_check_rules: list[str] = Field(default_factory=list)
    env_alert_reboot_pending_days: int = 7
    env_alert_unencrypted_scope: str = "laptops"
    # Compliance (C5): the grace of a critical update, and the members of
    # the local Administrators accepted beyond the built-in ones.
    compliance_patch_grace_days: int = 14
    env_compliance_patch_grace_days: int = 14
    compliance_admins_allowed: list[str] = Field(default_factory=list)
    # Licences (C6): how many days before its end a licence is « bientôt
    # échue ».
    license_expiry_days: int = 60
    env_license_expiry_days: int = 60
    # Schedules (C3): the zone the console plans in, and the weekly windows
    # when nothing at risk runs on several postes.
    console_timezone: str = "UTC"
    env_console_timezone: str = "UTC"
    forbidden_windows: list[dict[str, Any]] = Field(default_factory=list)
    # Reports (C4): whether a label's QR code opens the form without an account.
    reports_enabled: bool = False
    env_reports_enabled: bool = False
    # Two-person approval of mass actions (C10): on or off, the threshold,
    # how long a request waits; how many accounts could approve (places not
    # considered); the environment's values.
    approval_enabled: bool = False
    approval_threshold: int = 40
    approval_ttl_hours: int = 24
    approval_eligible: int = 0
    env_approval_enabled: bool = False
    env_approval_threshold: int = 40
    env_approval_ttl_hours: int = 24
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


class ForbiddenWindowIn(BaseModel):
    """A weekly range when nothing at risk runs on several postes: days
    (0 = Monday), from ``start`` to ``end`` local, within the day."""

    days: list[int] = Field(min_length=1, max_length=7)
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def _ordered(self) -> "ForbiddenWindowIn":
        if any(d < 0 or d > 6 for d in self.days):
            raise ValueError("a weekday is 0 (Monday) to 6")
        if self.start >= self.end:
            raise ValueError("a window ends after it starts, within the day")
        self.days = sorted(set(self.days))
        return self


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

    # Alerts. Lists are written whole; null hands the setting back to its
    # default (every rule on, nothing forbidden, no verification opened).
    alert_enabled_rules: list[AlertRule] | None = Field(
        default=None, max_length=len(ALL_RULES)
    )
    alert_reboot_pending_days: int | None = Field(default=None, ge=1, le=365)
    alert_warranty_days: int | None = Field(default=None, ge=1, le=365)
    alert_unencrypted_scope: Literal["laptops", "all"] | None = None
    alert_forbidden_software: (
        list[
            Annotated[
                str,
                StringConstraints(strip_whitespace=True, min_length=2, max_length=100),
            ]
        ]
        | None
    ) = Field(default=None, max_length=100)
    alert_auto_check_rules: list[AlertRule] | None = Field(
        default=None, max_length=len(ALL_RULES)
    )
    compliance_patch_grace_days: int | None = Field(default=None, ge=0, le=365)
    license_expiry_days: int | None = Field(default=None, ge=1, le=365)
    compliance_admins_allowed: (
        list[
            Annotated[
                str,
                StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
            ]
        ]
        | None
    ) = Field(default=None, max_length=100)

    # Schedules. A zone the server does not know is refused; null hands it
    # back to CONSOLE_TIMEZONE. Windows are written whole.
    console_timezone: str | None = Field(default=None, max_length=64)
    reports_enabled: bool | None = None
    # Two-person approval (C10): turning it on is refused with fewer than
    # two accounts able to approve.
    approval_enabled: bool | None = None
    approval_threshold: int | None = Field(default=None, ge=2, le=10000)
    approval_ttl_hours: int | None = Field(default=None, ge=1, le=168)
    forbidden_windows: list[ForbiddenWindowIn] | None = Field(
        default=None, max_length=20
    )

    @field_validator("console_timezone")
    @classmethod
    def _zone(cls, value: str | None) -> str | None:
        if value is not None and not windows.valid_zone(value):
            raise ValueError("unknown time zone")
        return value

    # How mail leaves: saved by its own card, so its fields arrive together.
    email: EmailSettingsIn | None = None


def _email_out(stored: mail.StoredEmailSettings) -> EmailSettingsOut:
    policy = mail.resolve(stored)
    from_env = mail.resolve(mail.StoredEmailSettings())
    v = stored.values
    held_back = mail.withheld(stored)
    missing = policy.missing()
    missing_codes = policy.missing_codes()
    # An SMTP account without its password logs in with an empty one: the
    # send fails. The page says what to do rather than « configuré ».
    smtp_login_broken = (
        policy.provider == "smtp"
        and "smtp_password" in held_back
        and bool(policy.smtp_user)
    )
    if smtp_login_broken:
        missing.append(mail.MISSING_LABELS["smtp_password_retype"])
        missing_codes.append("smtp_password_retype")
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
        configured=policy.enabled and not smtp_login_broken,
        missing=missing,
        missing_codes=missing_codes,
        withheld=held_back,
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
    alerts = await crud.alert_policy(session, values)
    compliance = await crud.compliance_policy(session, values)
    planning = await windows.schedule_policy(session, values)
    approvals = await crud.approval_policy(session, values)
    # Also refreshes what this process's ``queue_email`` reads: after a
    # patch, the new mail settings apply to the very next queued mail.
    stored = await mail.load_stored(session, values)
    owner = await session.get(User, policy.owner_id) if policy.owner_id else None
    stored_owner_raw = values.get(crud.KEY_OWNER)
    stored_owner: User | None = None
    if isinstance(stored_owner_raw, str) and stored_owner_raw:
        try:
            stored_owner_id = uuid.UUID(stored_owner_raw)
        except ValueError:
            stored_owner_id = None
        if stored_owner_id is not None and stored_owner_id != policy.owner_id:
            stored_owner = await session.get(User, stored_owner_id)
    latest = await session.exec(select(func.max(col(AppSetting.updated_at))))
    updated: datetime | None = latest.one()
    return SettingsOut(
        maintenance_default_cycle_days=policy.cycle_days,
        maintenance_default_owner=(
            UserRef(id=owner.id, name=owner.full_name or owner.email) if owner else None
        ),
        maintenance_default_owner_unavailable=(
            UserRef(
                id=stored_owner.id, name=stored_owner.full_name or stored_owner.email
            )
            if stored_owner
            else None
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
        alert_rules=[r.value for r in ALL_RULES],
        alert_enabled_rules=[
            r.value for r in ALL_RULES if r.value in alerts.enabled_rules
        ],
        alert_reboot_pending_days=alerts.reboot_pending_days,
        alert_warranty_days=alerts.warranty_days,
        env_alert_warranty_days=env.ALERT_WARRANTY_DAYS,
        alert_unencrypted_scope=alerts.unencrypted_scope,
        alert_forbidden_software=list(alerts.forbidden_software),
        alert_auto_check_rules=[
            r.value for r in ALL_RULES if r.value in alerts.auto_check_rules
        ],
        env_alert_reboot_pending_days=env.ALERT_REBOOT_PENDING_DAYS,
        env_alert_unencrypted_scope=env.ALERT_UNENCRYPTED_SCOPE,
        compliance_patch_grace_days=compliance.patch_grace_days,
        env_compliance_patch_grace_days=env.COMPLIANCE_PATCH_GRACE_DAYS,
        compliance_admins_allowed=list(compliance.admins_allowed),
        license_expiry_days=await crud.license_expiry_days(session, values),
        env_license_expiry_days=env.LICENSE_EXPIRY_DAYS,
        console_timezone=planning.zone_name,
        env_console_timezone=env.CONSOLE_TIMEZONE,
        forbidden_windows=[w.as_json() for w in planning.forbidden],
        reports_enabled=await report_crud.enabled(session, values),
        env_reports_enabled=env.REPORTS_ENABLED,
        approval_enabled=approvals.enabled,
        approval_threshold=approvals.threshold,
        approval_ttl_hours=approvals.ttl_hours,
        approval_eligible=await approval_reach.eligible_count(session),
        env_approval_enabled=env.APPROVAL_ENABLED,
        env_approval_threshold=env.APPROVAL_THRESHOLD,
        env_approval_ttl_hours=env.APPROVAL_TTL_HOURS,
        email=_email_out(stored),
        environment=[
            EnvGroupOut(
                code=group.code,
                label=group.label,
                items=[
                    EnvItemOut(
                        key=i.key,
                        value=i.value,
                        description=i.description,
                        raw=i.raw,
                        format=i.format,
                        params=i.params,
                    )
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
    "alert_reboot_pending_days": crud.KEY_ALERT_REBOOT_DAYS,
    "alert_warranty_days": crud.KEY_ALERT_WARRANTY_DAYS,
    "alert_unencrypted_scope": crud.KEY_ALERT_UNENCRYPTED_SCOPE,
    "console_timezone": windows.KEY_TIMEZONE,
    "reports_enabled": report_crud.KEY_ENABLED,
    "compliance_patch_grace_days": crud.KEY_COMPLIANCE_PATCH_GRACE,
    "license_expiry_days": crud.KEY_LICENSE_EXPIRY_DAYS,
    "approval_threshold": crud.KEY_APPROVAL_THRESHOLD,
    "approval_ttl_hours": crud.KEY_APPROVAL_TTL_HOURS,
}

# List settings: written whole, without duplicates, in the order sent.
_LIST_KEYS = {
    "alert_enabled_rules": crud.KEY_ALERT_RULES,
    "alert_forbidden_software": crud.KEY_ALERT_FORBIDDEN,
    "alert_auto_check_rules": crud.KEY_ALERT_AUTO_CHECK,
    "compliance_admins_allowed": crud.KEY_COMPLIANCE_ADMINS,
}


async def _write_lists(
    session: SessionDep, payload: SettingsUpdate, *, actor: str
) -> None:
    if "forbidden_windows" in payload.model_fields_set:
        sent_windows = payload.forbidden_windows
        await crud.set_value(
            session,
            windows.KEY_FORBIDDEN,
            None if sent_windows is None else [w.model_dump() for w in sent_windows],
            actor=actor,
        )
    for field in sorted(payload.model_fields_set & _LIST_KEYS.keys()):
        sent: list[str] | None = getattr(payload, field)
        value = None if sent is None else list(dict.fromkeys(str(v) for v in sent))
        await crud.set_value(session, _LIST_KEYS[field], value, actor=actor)


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
    zone_before = (await windows.schedule_policy(session)).zone
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
    if "console_timezone" in sent:
        # The schedules are planned in the console's zone: they keep their
        # hour in the new one (``schedule.runner.rezone``).
        from app.features.schedule import runner as schedule_runner

        await session.flush()
        planning = await windows.schedule_policy(session)
        if planning.zone != zone_before:
            await schedule_runner.rezone(session, zone_before, planning, utcnow())


async def _write_approval(
    session: SessionDep, payload: SettingsUpdate, *, actor: str
) -> None:
    """Turn two-person approval on or off (C10). On is refused while fewer
    than two accounts could approve: with a single administrator, every
    action of mass would wait for nobody. Off leaves the pending requests
    decidable until they expire."""
    if "approval_enabled" not in payload.model_fields_set:
        return
    value = payload.approval_enabled
    if value and not (await crud.approval_policy(session)).enabled:
        eligible = await approval_reach.eligible_count(session)
        if eligible < 2:
            raise AppError(
                code=ErrorCode.APPROVAL_NOT_ENOUGH_APPROVERS,
                status_code=422,
                message="Two accounts at least must be able to approve",
                details={"eligible": eligible},
            )
    await crud.set_value(session, crud.KEY_APPROVAL_ENABLED, value, actor=actor)


@router.get("", response_model=SettingsOut)
async def get_settings(session: SessionDep) -> SettingsOut:
    return await _out(session)


def _audit_value(value: object) -> str | None:
    """A setting as the audit line writes it: a list as its values joined —
    the codes of the rules, not the Python representation of the enums."""
    if value is None:
        return None
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        # Forbidden windows: « 0,1,2,3,4 08:00–12:00 ».
        return "; ".join(
            f"{','.join(str(d) for d in v.get('days', []))} "
            f"{v.get('start')}–{v.get('end')}"
            for v in value
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        # Each value once, as stored; an empty list (every rule turned off)
        # is not a null (back to the default, every rule on).
        values = list(dict.fromkeys(str(v) for v in value))
        return ", ".join(values) if values else "[]"
    return str(value)


@router.patch("", response_model=SettingsOut, dependencies=[_WRITE])
async def update_settings(
    payload: SettingsUpdate, session: SessionDep, current: CurrentUser
) -> SettingsOut:
    fields = payload.model_dump(exclude_unset=True, exclude={"email"})
    await _write_usage(session, payload, actor=current.email)
    await _write_simple(session, payload, actor=current.email)
    await _write_lists(session, payload, actor=current.email)
    await _write_approval(session, payload, actor=current.email)
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
        stored = (await crud.get_all(session)).get(crud.KEY_OWNER)
        # The card sends every field: re-sending an owner deactivated since
        # must not keep the cycle from being saved (audit B08).
        if owner_id is not None and str(owner_id) != stored:
            owner = await session.get(User, owner_id)
            if owner is None or not owner.is_active:
                raise AppError(
                    code=ErrorCode.USER_NOT_FOUND,
                    status_code=404,
                    message="User not found",
                )
            # Any poste with no owner of its own falls to the default one:
            # the rule of a poste's or a room's owner, over the whole parc.
            if not (await owner_reach(session, {owner.id})).parc(owner.id):
                raise AppError(
                    code=ErrorCode.MAINTENANCE_OWNER_OUT_OF_REACH,
                    status_code=422,
                    message=(
                        "The default owner must hold maintenance:read and "
                        "maintenance:write over the whole parc"
                    ),
                )
        await crud.set_value(
            session,
            crud.KEY_OWNER,
            str(owner_id) if owner_id else None,
            actor=current.email,
        )
    details: dict[str, str | None] = {k: _audit_value(v) for k, v in fields.items()}
    if payload.email is not None:
        _reject_secret_redirect(
            await mail.load_stored(session), payload.email.changes()
        )
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


def _reject_secret_redirect(
    stored: mail.StoredEmailSettings, changes: dict[str, Any]
) -> None:
    """Refuse to send a stored secret to a destination it was not typed for
    (``email_policy.secrets_to_retype``)."""
    missing = mail.secrets_to_retype(stored, changes)
    if missing:
        raise AppError(
            code=ErrorCode.SETTINGS_EMAIL_SECRET_REQUIRED,
            status_code=422,
            message="The server changed: type the password or API key again",
            details={"fields": missing},
        )


# --- Test send ----------------------------------------------------------------


class EmailTestIn(BaseModel):
    """A test send. ``to`` defaults to the caller's own address. ``email``
    carries the card's unsaved values, applied over what is stored exactly as
    a patch would apply them — so a server can be tried before it is saved,
    and a stored password need not be typed again to try a new sender. It
    must be, though, to try a new server: a stored secret never leaves for a
    destination it was not typed for (``_reject_secret_redirect``)."""

    to: Email | None = None
    email: EmailSettingsIn | None = None


class EmailTestOut(BaseModel):
    ok: bool
    # Readable as is, in French: what went out, or what to fix.
    message: str
    # The same as a code and its parameters, for a console that words it in
    # its reader's language (``app.features.notification.probe``). Null from
    # nothing this server sends; a console falls back to ``message``.
    code: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


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
    _reject_secret_redirect(stored, unsaved)
    policy = mail.resolve(stored.merged(unsaved))
    to = payload.to or current.email
    result = await probe.send_test(policy, to, language=current.language)
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
            # What the console words the message from, in its reader's
            # language (plan console bilingue): the same as the page's.
            "message_code": result.code,
            "message_params": result.params,
        },
    )
    await session.commit()
    return EmailTestOut(
        ok=result.ok, message=result.message, code=result.code, params=result.params
    )
