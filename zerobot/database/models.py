"""ORM models for users, bots, and wallets.

Each class maps 1:1 to a Postgres table and is wired up via SQLAlchemy 2.0's
``Mapped`` / ``mapped_column`` syntax. ``created_at`` defaults are stored in
UTC so that queries are timezone-stable across hosts.
"""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zerobot.database.engine import Base


class User(Base):
    """A platform user — typically a Telegram account mapped via ``tg-{id}``."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

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

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    owner = relationship("User", back_populates="bots")


class Wallet(Base):
    """The crystal balance owned by a single user."""

    __tablename__ = "wallets"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)

    user = relationship("User", back_populates="wallet")
