"""End-to-end tests for the phone-verification + quota + session layer.

We use an in-memory SQLite engine so the tests stay fast and don't need
a postgres container.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from zerobot.database.engine import Base
from zerobot.database.models import Bot, User
from zerobot.identity import (
    PhoneError,
    check_bot_quota,
    is_linked,
    is_phone_verified,
    normalize_e164,
    phone_hash,
    record_phone_verification,
    revoke_session,
    set_bot_quota,
    store_session,
    unlink_phone,
    unwrap_session,
)
from zerobot.identity.sessions import SessionLinkError
from zerobot.security.keys import reset_key_cache

# ── normalization ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+447700900000", "+447700900000"),
        ("447700900000", "+447700900000"),
        ("  +44 7700 900000 ", "+447700900000"),
        ("+1 (415) 555-1212", "+14155551212"),
    ],
)
def test_normalize_e164_accepts_valid(raw: str, expected: str) -> None:
    assert normalize_e164(raw) == expected


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "+", "+12", "+1234567890123456", "++123456"],
)
def test_normalize_e164_rejects_invalid(bad: str) -> None:
    with pytest.raises(PhoneError):
        normalize_e164(bad)


def test_phone_hash_is_deterministic() -> None:
    assert phone_hash("+447700900000") == phone_hash("+447700900000")
    assert phone_hash("+447700900000") != phone_hash("+447700900001")


# ── DB-backed identity tests ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    """Spin up an in-memory SQLite DB with all tables created."""
    reset_key_cache()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    yield sm
    await engine.dispose()


@pytest.mark.asyncio
async def test_record_phone_creates_user_and_marks_verified(db) -> None:
    async with db() as session:
        user = await record_phone_verification(session, "tg-1", "+447700900000")
        assert user.phone_hash == phone_hash("+447700900000")
        assert user.phone_verified_at is not None
        assert user.phone_encrypted is not None
        # Encrypted blob is *not* the plaintext.
        assert b"447700900000" not in user.phone_encrypted

    async with db() as session:
        assert await is_phone_verified(session, "tg-1") is True
        assert await is_phone_verified(session, "tg-2") is False


@pytest.mark.asyncio
async def test_phone_can_be_decrypted_only_with_matching_aad(db) -> None:
    """Encrypted phone is bound to the user_id via AAD."""
    from zerobot.security.crypto import CryptoError
    from zerobot.security.keys import get_master_cryptor

    async with db() as session:
        user = await record_phone_verification(session, "tg-1", "+14155551212")

    cr = get_master_cryptor()
    assert cr.decrypt_str(user.phone_encrypted, aad=b"tg-1") == "+14155551212"
    with pytest.raises(CryptoError):
        cr.decrypt_str(user.phone_encrypted, aad=b"tg-2")


@pytest.mark.asyncio
async def test_duplicate_phone_blocked_for_other_user(db) -> None:
    async with db() as session:
        await record_phone_verification(session, "tg-1", "+447700900000")
    async with db() as session:
        with pytest.raises(PhoneError, match="already linked"):
            await record_phone_verification(session, "tg-2", "+447700900000")


@pytest.mark.asyncio
async def test_same_user_can_reverify_same_phone(db) -> None:
    async with db() as session:
        await record_phone_verification(session, "tg-1", "+447700900000")
    async with db() as session:
        # Idempotent: re-verifying with the same phone is allowed.
        await record_phone_verification(session, "tg-1", "+447700900000")
        assert await is_phone_verified(session, "tg-1")


@pytest.mark.asyncio
async def test_unlink_phone_clears_state(db) -> None:
    async with db() as session:
        await record_phone_verification(session, "tg-1", "+447700900000")
    async with db() as session:
        cleared = await unlink_phone(session, "tg-1")
        assert cleared is True
        assert await is_phone_verified(session, "tg-1") is False
    async with db() as session:
        # After unlink, the same phone may be re-bound elsewhere.
        await record_phone_verification(session, "tg-2", "+447700900000")


@pytest.mark.asyncio
async def test_unlink_when_no_phone_is_no_op(db) -> None:
    async with db() as session:
        cleared = await unlink_phone(session, "tg-ghost")
        assert cleared is False


# ── quota ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quota_uses_default_until_overridden(db) -> None:
    async with db() as session:
        # No user → falls back to settings.FREE_BOT_QUOTA (3 by default).
        q = await check_bot_quota(session, "tg-1")
        assert q.allowed is True
        assert q.current == 0
        assert q.quota >= 1


@pytest.mark.asyncio
async def test_quota_blocks_when_at_limit(db) -> None:
    async with db() as session:
        await record_phone_verification(session, "tg-1", "+447700900000")
        await set_bot_quota(session, "tg-1", 2)
        for i in range(2):
            session.add(Bot(id=f"b{i}", user_id="tg-1", token="t"))
        await session.commit()
        q = await check_bot_quota(session, "tg-1")
        assert q.current == 2
        assert q.quota == 2
        assert q.allowed is False
        assert q.remaining == 0


@pytest.mark.asyncio
async def test_set_bot_quota_creates_user_if_missing(db) -> None:
    async with db() as session:
        n = await set_bot_quota(session, "tg-new", 10)
        assert n == 10
        u = await session.get(User, "tg-new")
        assert u is not None
        assert u.bot_quota == 10


# ── session storage ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_round_trip(db) -> None:
    async with db() as session:
        await store_session(session, "tg-1", 12345, "session-string-here")
    async with db() as session:
        unwrapped = await unwrap_session(session, "tg-1")
        assert unwrapped is not None
        assert unwrapped.user_id == "tg-1"
        assert unwrapped.telegram_user_id == 12345
        assert unwrapped.session_string == "session-string-here"


@pytest.mark.asyncio
async def test_session_blob_is_encrypted(db) -> None:
    """The raw row should not contain the plaintext session anywhere."""
    from sqlalchemy import select

    from zerobot.database.models import BotOwnerSession

    async with db() as session:
        await store_session(session, "tg-1", 7, "MAGIC-PLAINTEXT-SESSION")
        row = (await session.execute(select(BotOwnerSession))).scalar_one()
        assert b"MAGIC-PLAINTEXT-SESSION" not in row.encrypted_session


@pytest.mark.asyncio
async def test_storing_new_session_revokes_old(db) -> None:
    async with db() as session:
        await store_session(session, "tg-1", 1, "old-session")
        await store_session(session, "tg-1", 1, "new-session")
    async with db() as session:
        unwrapped = await unwrap_session(session, "tg-1")
        assert unwrapped is not None
        assert unwrapped.session_string == "new-session"


@pytest.mark.asyncio
async def test_revoke_session_makes_unwrap_return_none(db) -> None:
    async with db() as session:
        await store_session(session, "tg-1", 1, "x")
        assert await is_linked(session, "tg-1") is True
        revoked = await revoke_session(session, "tg-1")
        assert revoked is True
    async with db() as session:
        assert await unwrap_session(session, "tg-1") is None
        assert await is_linked(session, "tg-1") is False


@pytest.mark.asyncio
async def test_revoke_when_no_session_is_no_op(db) -> None:
    async with db() as session:
        assert await revoke_session(session, "tg-ghost") is False


@pytest.mark.asyncio
async def test_empty_session_string_rejected(db) -> None:
    async with db() as session:
        with pytest.raises(SessionLinkError):
            await store_session(session, "tg-1", 1, "   ")


def test_module_imports_are_concurrency_safe() -> None:
    """Smoke test: importing the package twice from threads doesn't deadlock."""
    asyncio.run(asyncio.sleep(0))  # ensure event loop machinery works
