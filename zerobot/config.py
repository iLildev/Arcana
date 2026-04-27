"""Application configuration loaded from environment variables.

Settings are parsed by ``pydantic-settings``; values can be overridden by an
``.env`` file at the project root or by real environment variables. See
``.env.example`` for the full set of supported keys.
"""

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for every ZeroBot service.

    Values are read once at import time and cached in the module-level
    ``settings`` singleton below. Mutating ``settings`` at runtime is not
    supported and may break long-lived clients (e.g. the SQLAlchemy engine).
    """

    # ── Database ───────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/zerobot"

    # ── Wallet / billing ───────────────────────────────────────────────────
    INITIAL_CRYSTALS: int = 10  # crystals granted on first wallet creation

    # ── Port registry ──────────────────────────────────────────────────────
    PORT_RANGE_START: int = 30000
    PORT_RANGE_END: int = 30100

    # ── Admin console ──────────────────────────────────────────────────────
    ADMIN_TOKEN: str = ""  # required header value to call /admin/* routes
    ADMIN_USER_ID: str = ""  # the developer's user id (owner of official bots)

    # ── Hibernation ────────────────────────────────────────────────────────
    HIBERNATION_TIMEOUT: int = 1800  # seconds of inactivity before reaping
    HIBERNATION_SWEEP: int = 30  # seconds between hibernator sweep cycles

    # ── Events (publisher → manager bot) ───────────────────────────────────
    EVENT_SHARED_SECRET: str = ""  # HMAC-SHA256 secret; empty disables signing

    # ── Builder Agent ──────────────────────────────────────────────────────
    BUILDER_SESSION_DIR: str = "runtime_envs/builder_sessions"

    # ── Sandbox resource limits (Linux only; ignored on platforms without
    # the ``resource`` module). Set any value to 0 to disable that limit.
    SANDBOX_CPU_SECONDS: int = 30  # max CPU seconds per bash invocation
    SANDBOX_MEM_MB: int = 512  # max address-space (RSS) per process
    SANDBOX_FILE_MB: int = 50  # max single-file size written by sandbox
    SANDBOX_MAX_PROCS: int = 64  # max concurrent processes per sandbox call

    # ── Identity (Phase 0) ────────────────────────────────────────────────
    # Base64-encoded 32-byte AES-256 master key for at-rest encryption of
    # phone numbers and MTProto sessions. Falls back to a deterministic
    # dev key (with a loud warning) when unset.
    MASTER_ENCRYPTION_KEY: str = ""
    # Base64-encoded HMAC key used to dedupe phone numbers without
    # decrypting them. Same fallback policy as MASTER_ENCRYPTION_KEY.
    PHONE_HMAC_KEY: str = ""
    # How many bots a verified user may plant for free.
    FREE_BOT_QUOTA: int = 3
    # When True, the platform refuses to create bots / run agent turns
    # for users who haven't shared a phone via Telegram contact.
    REQUIRE_PHONE_VERIFICATION: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_async_url(cls, v: str) -> str:
        """Force the asyncpg driver and strip query params it does not accept.

        Many hosting providers hand out URLs in the ``postgres://`` /
        ``postgresql://`` form with an ``sslmode=...`` query parameter. The
        synchronous psycopg dialect understands these, but ``asyncpg`` does
        not, so we rewrite both before SQLAlchemy ever sees the URL.
        """
        parsed = urlparse(v)
        scheme = parsed.scheme
        if scheme in ("postgres", "postgresql"):
            scheme = "postgresql+asyncpg"
        query = dict(parse_qsl(parsed.query))
        query.pop("sslmode", None)
        return urlunparse(parsed._replace(scheme=scheme, query=urlencode(query)))


settings = Settings()
