from typing import Annotated, Any, Literal, Self

from pydantic import AnyUrl, BeforeValidator, computed_field, model_validator
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

    PROJECT_NAME: str = "Tiai"
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
    # endpoints, plan §2.2) but the backend and ARQ worker share Postgres, so
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

    # --- Redis (ARQ queue) ---
    REDIS_SERVER: str = "redis"
    REDIS_PORT: int = 6379

    # --- Mailgun (alert e-mails) ---
    MAILGUN_API_BASE_URL: str = "https://api.mailgun.net/v3"
    MAILGUN_DOMAIN: str | None = None
    MAILGUN_API_KEY: str | None = None
    MAILGUN_FROM_EMAIL: str | None = None
    MAILGUN_FROM_NAME: str | None = "Tiai"
    MAILGUN_TIMEOUT_SECONDS: int = 10
    ALERT_RECIPIENTS: Annotated[list[str] | str, BeforeValidator(parse_list)] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def alerts_enabled(self) -> bool:
        """Whether Mailgun is configured."""
        return bool(self.MAILGUN_DOMAIN and self.MAILGUN_API_KEY)

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
