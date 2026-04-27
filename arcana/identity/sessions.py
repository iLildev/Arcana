"""MTProto user-session storage (encrypted at rest).

This is the substrate for the BotFather automation that lands in
Phase 1.ج. It only handles **persistence**: encrypting a session string,
storing it bound to a user, retrieving + decrypting on demand, and
revoking. The actual MTProto login flow (talking to Telegram, sending a
code, receiving the session string) is wired up in a later phase.

Why we encrypt with AAD = user_id:
- A leaked encrypted blob can't be replayed against a different user
  even if the attacker swaps the row's ``user_id`` field, because the
  AEAD tag is bound to the user_id we passed at encryption time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arcana.database.models import BotOwnerSession
from arcana.security.keys import get_master_cryptor


def _utc_naive() -> datetime:
    """Return the current UTC instant as a naive datetime (SQLAlchemy column type)."""
    return datetime.now(UTC).replace(tzinfo=None)


class SessionLinkError(Exception):
    """Raised on missing/revoked sessions or decryption failures."""


class LinkedSession(NamedTuple):
    """Decrypted MTProto session ready to be handed to Telethon/Pyrogram."""

    user_id: str
    telegram_user_id: int
    session_string: str
    created_at: datetime


async def store_session(
    session: AsyncSession,
    user_id: str,
    telegram_user_id: int,
    session_string: str,
) -> BotOwnerSession:
    """Encrypt *session_string* and persist it for *user_id*.

    If the user already has an active session, the old one is marked
    revoked so we always have at most one live row per user. The audit
    trail of past sessions is preserved.
    """
    if not session_string or not session_string.strip():
        raise SessionLinkError("session_string is empty")

    # Revoke any currently-active session for this user.
    existing = await session.scalar(
        select(BotOwnerSession).where(
            BotOwnerSession.user_id == user_id,
            BotOwnerSession.revoked_at.is_(None),
        )
    )
    if existing is not None:
        existing.revoked_at = _utc_naive()

    cryptor = get_master_cryptor()
    encrypted = cryptor.encrypt_str(session_string, aad=user_id.encode("utf-8"))

    row = BotOwnerSession(
        user_id=user_id,
        telegram_user_id=int(telegram_user_id),
        encrypted_session=encrypted,
        encryption_key_version=cryptor.version,
    )
    session.add(row)
    await session.commit()
    return row


async def unwrap_session(session: AsyncSession, user_id: str) -> LinkedSession | None:
    """Decrypt and return the user's active session, or ``None`` if none."""
    row = await session.scalar(
        select(BotOwnerSession).where(
            BotOwnerSession.user_id == user_id,
            BotOwnerSession.revoked_at.is_(None),
        )
    )
    if row is None:
        return None

    cryptor = get_master_cryptor()
    try:
        plaintext = cryptor.decrypt_str(row.encrypted_session, aad=user_id.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SessionLinkError(f"failed to decrypt session for {user_id}: {exc}") from exc

    # Touch last_used_at on every successful unwrap (cheap, useful for audit).
    row.last_used_at = _utc_naive()
    await session.commit()

    return LinkedSession(
        user_id=row.user_id,
        telegram_user_id=row.telegram_user_id,
        session_string=plaintext,
        created_at=row.created_at,
    )


async def revoke_session(
    session: AsyncSession,
    user_id: str,
) -> bool:
    """Revoke the user's active session. Returns True if anything changed."""
    row = await session.scalar(
        select(BotOwnerSession).where(
            BotOwnerSession.user_id == user_id,
            BotOwnerSession.revoked_at.is_(None),
        )
    )
    if row is None:
        return False
    row.revoked_at = _utc_naive()
    await session.commit()
    return True


async def is_linked(session: AsyncSession, user_id: str) -> bool:
    """Cheap boolean: does the user have an active linked Telegram session?"""
    row = await session.scalar(
        select(BotOwnerSession.user_id).where(
            BotOwnerSession.user_id == user_id,
            BotOwnerSession.revoked_at.is_(None),
        )
    )
    return row is not None
