"""ORM models for users, bots, wallets, identity, and audit logs.

Each class maps 1:1 to a Postgres table and is wired up via SQLAlchemy 2.0's
``Mapped`` / ``mapped_column`` syntax. ``created_at`` defaults are stored in
UTC so that queries are timezone-stable across hosts.

Phase 0 added the identity layer:
- ``User`` gained encrypted phone fields, a searchable HMAC, and a per-user
  bot quota override.
- ``BotOwnerSession`` stores encrypted MTProto user-sessions for BotFather
  automation (one active row per user).
- ``PhoneVerificationLog`` and ``BotFatherOperation`` are append-only audit
  trails for sensitive identity / BotFather actions.
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zerobot.database.engine import Base


def _utc_now() -> datetime:
    """Return the current UTC time. Replaces the deprecated ``datetime.utcnow``."""
    return datetime.now(UTC)


class User(Base):
    """A platform user — typically a Telegram account mapped via ``tg-{id}``."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=_utc_now)

    # ── Phase 0: identity / phone verification ────────────────────────────
    # AES-GCM envelope of the E.164 phone, AAD-bound to ``id``. ``None`` when
    # the user has not yet shared a contact card.
    phone_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # HMAC-SHA256(phone_e164) for dedup + lookup without decryption.
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    # Set on the most recent successful verification; cleared on unlink.
    phone_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Per-user quota override; ``None`` falls back to ``settings.FREE_BOT_QUOTA``.
    bot_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Reverse-relations populated by SQLAlchemy on attribute access.
    bots = relationship("Bot", back_populates="owner")
    wallet = relationship("Wallet", back_populates="user", uselist=False)


class Bot(Base):
    """A Telegram bot planted by a user (or by the platform owner)."""

    __tablename__ = "bots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    token: Mapped[str] = mapped_column(String)

    # Lifecycle flags. ``is_active`` means a process is currently running;
    # ``is_hibernated`` means the bot has been reaped and needs to be woken
    # before its next message can be delivered. ``is_official`` marks bots
    # owned by the platform admin (they are exempt from billing).
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hibernated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)

    name: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)

    # Set while the bot is awake; ``None`` while hibernated.
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_utc_now)

    owner = relationship("User", back_populates="bots")


class Wallet(Base):
    """The crystal balance owned by a single user."""

    __tablename__ = "wallets"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)

    user = relationship("User", back_populates="wallet")


# ═══════════════════════════ Phase 0: identity ═══════════════════════════


class BotOwnerSession(Base):
    """An MTProto user-session linked to a ZeroBot user.

    Stored encrypted at rest so that even a database snapshot does not
    leak the plaintext session string. Exactly one row per user may be
    in the "active" state (``revoked_at IS NULL``); older sessions are
    kept for audit but their ``revoked_at`` is set when superseded.
    """

    __tablename__ = "bot_owner_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer)

    encrypted_session: Mapped[bytes] = mapped_column(LargeBinary)
    encryption_key_version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(default=_utc_now)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class PhoneVerificationLog(Base):
    """Append-only audit trail of every verify / unlink event.

    Used for compliance ("prove the user really asked for deletion"), for
    abuse forensics, and for rate-limiting future verification attempts.
    """

    __tablename__ = "phone_verification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(16))  # 'verify' | 'unlink'
    source: Mapped[str] = mapped_column(String(32))  # 'telegram_contact' | …
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utc_now)

    __table_args__ = (Index("ix_pv_log_user_created", "user_id", "created_at"),)


class BotFatherOperation(Base):
    """Audit row for any operation we performed against @BotFather.

    Phase 0 ships the schema only. Rows start being written in Phase 1.ج
    once the BotFather automation goes live.
    """

    __tablename__ = "botfather_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    bot_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    op_type: Mapped[str] = mapped_column(String(48))  # 'rename' | 'set_photo' | …
    payload_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utc_now)
