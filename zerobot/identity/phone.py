"""Phone-number verification — normalization, hashing, persistence.

The phone itself is stored encrypted at rest in ``users.phone_encrypted``.
We additionally store a deterministic HMAC of the E.164 form in
``users.phone_hash`` so we can:

1. Look up a user by phone (without decrypting every row).
2. Reject duplicate registrations (one phone → one account).

Verification is recorded by :func:`record_phone_verification`, which
also writes an audit row to ``phone_verification_log``.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zerobot.database.models import PhoneVerificationLog, User
from zerobot.security.crypto import hmac_sha256
from zerobot.security.keys import get_master_cryptor, get_phone_hmac_key

# Strict E.164: leading +, then 6..15 digits. Telegram contacts always
# send an E.164 number without the leading +, so we re-add it ourselves.
_E164_RE = re.compile(r"^\+\d{6,15}$")


class PhoneError(ValueError):
    """Raised on invalid input or duplicate-phone collisions."""


# ── normalization ─────────────────────────────────────────────────────────


def normalize_e164(raw: str) -> str:
    """Trim whitespace and force a leading ``+``; reject anything non-conforming.

    Telegram's ``Contact.phone_number`` is already digits-only (no '+'),
    so we add it back. We deliberately do **not** pull in a heavy library
    like ``phonenumbers`` for Phase 0 — the format check is enough to
    catch typos without false-positive country-rule rejections.
    """
    if not raw:
        raise PhoneError("phone number is empty")
    s = re.sub(r"[\s\-()]", "", str(raw)).strip()
    if not s.startswith("+"):
        s = "+" + s.lstrip("+")
    if not _E164_RE.match(s):
        raise PhoneError(f"not a valid E.164 phone number: {raw!r}")
    return s


def phone_hash(phone_e164: str) -> str:
    """Return the searchable HMAC-SHA256 of an E.164 phone."""
    return hmac_sha256(get_phone_hmac_key(), phone_e164.encode("utf-8"))


# ── persistence ───────────────────────────────────────────────────────────


async def record_phone_verification(
    session: AsyncSession,
    user_id: str,
    raw_phone: str,
    *,
    source: str = "telegram_contact",
    ip_hash: str | None = None,
) -> User:
    """Persist a successful phone verification for *user_id*.

    Idempotent: re-verifying with the same phone is a no-op (just updates
    ``phone_verified_at``). Re-verifying with a *different* phone is
    allowed; the new value replaces the old one.

    Raises :class:`PhoneError` when:
    - the phone is not parseable;
    - another user is already bound to this phone (sybil block).
    """
    phone_e164 = normalize_e164(raw_phone)
    h = phone_hash(phone_e164)

    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        session.add(user)
        await session.flush()

    # Sybil check: refuse if a *different* user already owns this hash.
    other = await session.scalar(
        select(User).where(User.phone_hash == h, User.id != user_id)
    )
    if other is not None:
        raise PhoneError(
            f"this phone is already linked to another account ({other.id}); "
            "unlink it there first"
        )

    cryptor = get_master_cryptor()
    user.phone_encrypted = cryptor.encrypt_str(phone_e164, aad=user_id.encode("utf-8"))
    user.phone_hash = h
    user.phone_verified_at = datetime.utcnow()  # noqa: DTZ003 - SQLA stores naive UTC

    session.add(
        PhoneVerificationLog(
            user_id=user_id,
            phone_hash=h,
            action="verify",
            source=source,
            ip_hash=ip_hash,
        )
    )
    await session.commit()
    return user


async def unlink_phone(
    session: AsyncSession,
    user_id: str,
    *,
    source: str = "user_request",
) -> bool:
    """Clear all phone state for *user_id* (GDPR-style "delete my data").

    Returns ``True`` if anything was actually cleared. Logs an audit row
    so we can prove the deletion happened on demand.
    """
    user = await session.get(User, user_id)
    if user is None or user.phone_hash is None:
        return False

    log_hash = user.phone_hash
    user.phone_encrypted = None
    user.phone_hash = None
    user.phone_verified_at = None

    session.add(
        PhoneVerificationLog(
            user_id=user_id,
            phone_hash=log_hash,
            action="unlink",
            source=source,
        )
    )
    await session.commit()
    return True


async def is_phone_verified(session: AsyncSession, user_id: str) -> bool:
    """Quick boolean check used by gate decorators on the bots."""
    user = await session.get(User, user_id)
    return bool(user and user.phone_verified_at is not None)
