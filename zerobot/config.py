"""Application configuration loaded from environment variables.

Settings are parsed by ``pydantic-settings``; values can be overridden by an
``.env`` file at the project root or by real environment variables. See
``.env.example`` for the full set of supported keys.
"""

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import field_validator
from pydantic_settings import BaseSettings


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

    class Config:
        """Pydantic-settings configuration."""

        env_file = ".env"

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
