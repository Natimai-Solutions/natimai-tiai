from typing import Annotated, Any, Literal, Self

from pydantic import AnyUrl, BeforeValidator, Field, computed_field, model_validator
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_list(v: Any) -> list[str] | str:
    """Parse a comma-separated string into a list (env-friendly)."""
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    if isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    PROJECT_NAME: str = "Tia'i"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    SECRET_KEY: str = "changeme"

    # --- Console auth (admin users) ---
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8
    # First admin, seeded at startup if it does not exist yet.
    FIRST_ADMIN_EMAIL: str | None = None
    FIRST_ADMIN_PASSWORD: str | None = None
    # Minimum length for any password set through the API (console forms and
    # admin resets alike). Not applied to crud.create_user, used by seeding.
    PASSWORD_MIN_LENGTH: int = 12
    # Lifetime of a "forgot password" link.
    PASSWORD_RESET_EXPIRE_MINUTES: int = 60
    # Public console URL, used to build the reset link mailed to the user
    # (e.g. https://tiai.natimai.local). Without it, no reset mail can be sent.
    CONSOLE_BASE_URL: str | None = None

    # --- Agent enrollment ---
    # Shared secret deployed by GPO; only authorizes POST /agent/enroll.
    ENROLLMENT_SECRET: str = "changeme-enrollment-secret"

    # --- Remote commands ---
    # How long a queued command stays valid when the request does not carry its
    # own ``ttl_minutes``. Past it, a command *still pending* is expired: it is
    # never handed to an agent again, so a poste powered back on weeks later does
    # not run what was asked of it in the meantime. An hour is ample for a poste
    # that is on — the agent beats every 60 s; raise it on a parc whose postes
    # are only on intermittently, lower it where a command is worth nothing
    # outside the moment it was queued. Only PENDING commands are swept: once
    # delivered, the command belongs to the agent.
    #
    # Bounded like the request field (1 min → 30 d), and here rather than on the
    # route so that a mistyped `.env` refuses to boot instead of failing every
    # queueing call.
    COMMAND_DEFAULT_TTL_MINUTES: int = Field(default=60, ge=1, le=60 * 24 * 30)

    # --- Rate limiting ---
    # Escape hatch, not a tuning knob: the per-endpoint budgets live with the
    # limiters (app.core.ratelimit). Off only for a deployment whose operators
    # all arrive from one shared address (VPN, proxy) and lock each other out.
    RATE_LIMIT_ENABLED: bool = True

    # --- CORS ---
    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_list)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        """All allowed CORS origins."""
        return [str(o).rstrip("/") for o in self.BACKEND_CORS_ORIGINS]

    # --- PostgreSQL ---
    POSTGRES_SERVER: str = "db"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "tiai"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "tiai"

    # Async connection pool (psycopg 3). Load is light (~1–3 req/s for 1000
    # endpoints, plan §2.2) but the backend and the worker share Postgres, so
    # the pool is tunable per deployment.
    POSTGRES_POOL_SIZE: int = 20
    POSTGRES_MAX_OVERFLOW: int = 10
    POSTGRES_POOL_TIMEOUT: int = 30

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Async SQLAlchemy DSN (psycopg 3)."""
        return str(
            MultiHostUrl.build(
                scheme="postgresql+psycopg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_SERVER,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    # --- Mailgun (outgoing e-mail) ---
    # Who receives what is not configured here: it is a per-account setting read
    # from the ``users`` table (``EmailPreference``). These say how mail leaves,
    # never to whom.
    MAILGUN_API_BASE_URL: str = "https://api.mailgun.net/v3"
    MAILGUN_DOMAIN: str | None = None
    MAILGUN_API_KEY: str | None = None
    MAILGUN_FROM_EMAIL: str | None = None
    MAILGUN_FROM_NAME: str | None = "Tia'i"
    MAILGUN_TIMEOUT_SECONDS: int = 10
    # Outbound HTTP proxy for the Mailgun client alone (e.g. "http://10.0.0.1:3128").
    # School networks often force outbound traffic through a proxy; a dedicated
    # variable keeps that detour scoped to this one client — the standard
    # HTTP_PROXY/HTTPS_PROXY names would be honoured by every process handed the
    # environment, Caddy included, which must keep talking to its upstreams
    # directly.
    MAILGUN_PROXY_URL: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def alerts_enabled(self) -> bool:
        """Whether Mailgun is configured."""
        return bool(self.MAILGUN_DOMAIN and self.MAILGUN_API_KEY)

    # --- E-mail outbox ---
    # Every mail is a row in ``email_outbox`` before it is a Mailgun request;
    # the worker drains the table and retries failures with an exponential
    # backoff (1 min doubling to a 1 h ceiling). After this many attempts —
    # roughly 14 hours, enough to ride out a night-long proxy or Mailgun
    # outage — the row is marked abandoned and kept with its last error.
    EMAIL_MAX_ATTEMPTS: int = 20
    # How long sent and abandoned rows stay in the table before the daily purge
    # drops them. Pending rows are never purged: a mail still owed is not
    # clutter, whatever its age.
    EMAIL_OUTBOX_RETENTION_DAYS: int = 30

    # --- Notifications sent to console accounts ---
    # Hour (UTC) the daily digest goes out. The parc this console was built for
    # sits at UTC-10, where 18:00 UTC is 08:00 local — a digest that lands with
    # the morning coffee rather than in the middle of the night. Move it to suit
    # the deployment: the job reads the fleet's current state, so the hour only
    # decides when someone is told, never what they are told.
    # Bounded, because the failure is silent: a daily job aimed at hour 25
    # never comes due on any day, so the digest would simply never run and
    # nothing would say why.
    DIGEST_HOUR_UTC: int = Field(default=18, ge=0, le=23)
    # A detection older than this never triggers an immediate alert. A poste
    # enrolling for the first time hands over Defender's *entire* detection
    # history in one heartbeat; without this, joining a machine to the parc
    # would mail out years-old threats as if they had just happened.
    THREAT_ALERT_MAX_AGE_HOURS: int = 24
    # How many machines or detections a single mail spells out before falling
    # back on "… et N autres". A digest is a nudge to open the console, not a
    # report to work from — and a fleet-wide outage must not send a mail with
    # three hundred lines in it.
    NOTIFICATION_MAX_ITEMS: int = 10

    # --- Defender freshness policy ---
    # A machine is "up to date" if signatures are younger than this many days.
    SIGNATURE_MAX_AGE_DAYS: int = 3
    # A machine is considered inactive after this many days without heartbeat.
    INACTIVE_AFTER_DAYS: int = 30
    # A machine counts as *online* (powered on, agent reachable) when its last
    # heartbeat is younger than this. Three times the agent's 60 s default poll,
    # not one: a single missed beat — a network blip, a server restart, the
    # agent's own retry back-off — must not flash the whole parc as off. Three
    # minutes still flips a poste within a few minutes of a real shutdown.
    # Raise it in step with `heartbeat_interval_seconds` on a slower parc.
    OFFLINE_AFTER_SECONDS: int = 180

    # --- Inventory thresholds ---
    # Below this much free space on the system volume, a poste is counted on the
    # dashboard and can be filtered for. Ten percent because that is roughly
    # where Windows Update starts failing to stage a cumulative update — the
    # symptom being a poste that quietly stops patching, which is the other
    # module's problem and this one's early warning.
    LOW_DISK_FREE_PERCENT: int = 10
    # Past this age — read off the BIOS date, the only age a poste knows about
    # itself — a machine is counted as due for renewal. Five years is a default,
    # not a policy: parcs amortise on their own schedule, hence a setting.
    HARDWARE_AGING_YEARS: int = 5

    # --- Agent version ---
    # The version every poste should be running. Left empty, the reference is
    # the highest version reported anywhere on the parc — right the morning
    # after a deployment, with no call to GitHub a server on an internal
    # network could not make. Set it to flag against a chosen version instead:
    # a parc rolling out to a pilot group first does not want the rest of the
    # fleet reported as behind on the pilot's account.
    AGENT_EXPECTED_VERSION: str | None = None

    # --- Maintenance ---
    # The parc-wide cycle, in days, a poste is due for a maintenance visit
    # after — unless its room or itself says otherwise, and unless the console
    # has written another default (``app_settings``, page Paramètres), which
    # then wins over this. Ninety days is a starting point, not a policy.
    MAINTENANCE_DEFAULT_CYCLE_DAYS: int = Field(default=90, ge=0, le=3650)
    # How many days before its due date a poste is reported "à échéance".
    MAINTENANCE_DUE_SOON_DAYS: int = Field(default=14, ge=0, le=365)

    # --- Rooms ---
    # How postes are filed into rooms. ``manual``: from the console, by hand.
    # ``ad_ou``: by the organisational unit the computer object sits in — the
    # agent reads its own DN off the registry, no directory round trip — one
    # room per OU, named after it. ``ad_location``: by the "location"
    # attribute of the computer object (the Emplacement field of ADUC), which
    # the agent reads through ADSI. In either directory mode the console can
    # no longer move a poste by hand: the directory is the source of truth,
    # and a placement it would overwrite on the next inventory is a placement
    # nobody can rely on. Rooms created this way keep their name, building and
    # settings editable — only the membership is the directory's.
    ROOM_SOURCE: Literal["manual", "ad_ou", "ad_location"] = "manual"

    # --- Wake-on-LAN ---
    # The magic packet is emitted by the server, not by an agent: the machine it
    # targets is off, and the whole point is to reach it anyway. What it needs is
    # a destination on the poste's own network segment — a NIC in standby only
    # ever sees frames broadcast on the wire it is plugged into.
    #
    # WOL_SUBNET_PREFIXLEN is a *fallback*. The mask normally comes from the
    # poste itself — its agent reads it off the adapter and reports it with the
    # address — which is the only source that can be right on a parc where /16
    # and /24 segments coexist. This applies to a poste whose agent predates that
    # reporting, or whose adapter did not expose a mask: 192.168.1.42 at /24 →
    # 192.168.1.255. /32 degrades to a unicast to the address itself, which only
    # wakes a poste whose ARP entry is still alive upstream.
    WOL_SUBNET_PREFIXLEN: int = 24
    # Explicit broadcast addresses, comma-separated. When set they *replace* the
    # derived one and every poste is woken through all of them — the answer for a
    # server that must reach segments it has no address on, and the only way to
    # wake a poste that has never reported an address.
    WOL_BROADCAST_ADDRESSES: Annotated[
        list[str] | str, BeforeValidator(parse_list)
    ] = []
    # UDP/9 (discard) by convention. The port is immaterial to the hardware — a
    # NIC in standby matches the magic pattern anywhere in the frame — so this
    # only ever matters to a firewall on the way.
    WOL_PORT: int = 9
    # UDP over a broadcast is unacknowledged and dropped without notice; three
    # copies cost three datagrams and remove the single-loss case.
    WOL_PACKET_COUNT: int = 3

    # --- Wake-on-LAN relayed by an agent ---
    # For a server that is nowhere near the postes — hosted off-site, or in a
    # cloud — and therefore cannot put a frame on their wire at all. Enabled,
    # the server stops emitting and instead hands the wake to *another poste of
    # the same site*: the first machine sharing the target's location (or, for
    # a target with no location, its domain) to contact the server receives the
    # target's MAC and broadcasts the magic packet on its own subnets. Off by
    # default because it changes what the wake button does, and because the
    # relay is the one command in the catalogue that carries an argument — the
    # agent bounds it (an EUI-48, its own subnets only), but it is still a
    # choice a deployment makes knowingly. Either mode, never both: a remote
    # server emitting into the void would only report a success it cannot have.
    WOL_RELAY_ENABLED: bool = False
    # How long a relayed wake waits for a poste to claim it before expiring. Ten
    # minutes and not the general command TTL: a wake nobody relayed within ten
    # minutes is a site with nothing on, and a magic packet an hour late meets
    # a poste somebody already switched on by hand.
    WOL_RELAY_TTL_MINUTES: int = Field(default=10, ge=1, le=60 * 24)
    # A poste on the *same subnet* as the target claims the wake at once; a
    # poste merely on the same site waits this long first, leaving the better
    # placed one — the one whose broadcast is certain to reach the target — a
    # heartbeat's head start. Slightly above the agent's 60 s poll so that
    # head start is a full cycle. Zero disables the preference.
    WOL_RELAY_SUBNET_GRACE_SECONDS: int = Field(default=90, ge=0)

    @model_validator(mode="after")
    def _refuse_placeholder_secrets(self) -> Self:
        """Fail fast outside `local` when a secret is empty or a placeholder.

        Guards against an incomplete deploy `.env`: booting production with
        `SECRET_KEY=changeme` would make every console JWT forgeable (plan §7).
        Placeholders in code defaults and deploy/.env.example all start with
        "changeme".
        """
        if self.ENVIRONMENT == "local":
            return self
        for name in (
            "SECRET_KEY",
            "ENROLLMENT_SECRET",
            "POSTGRES_PASSWORD",
            "FIRST_ADMIN_PASSWORD",
        ):
            value: str | None = getattr(self, name)
            if value is None:
                continue
            if not value or value.startswith("changeme"):
                raise ValueError(
                    f"{name} is empty or still a 'changeme' placeholder; refusing "
                    f"to start in {self.ENVIRONMENT} (see deploy/.env.example)"
                )
        return self


settings = Settings()
