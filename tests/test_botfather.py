"""Tests for the BotFather automation layer (Phase 1.ج, Bot API portion)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from zerobot.botfather import (
    BotCommand,
    BotFatherClient,
    BotFatherError,
    fetch_bot_profile,
    update_bot_profile,
)
from zerobot.database.models import Base, Bot, BotFatherOperation, User

pytestmark = pytest.mark.asyncio


# ─────────────────────── Test infrastructure ────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_bot(db_session):
    """A user owning one bot, both persisted and ready for ownership checks."""
    user = User(id="u1")
    bot = Bot(id="b1", user_id="u1", token="123:FAKE")
    db_session.add_all([user, bot])
    await db_session.commit()
    return bot


def _mock_transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _ok(result):
    return httpx.Response(200, json={"ok": True, "result": result})


def _err(description: str, code: int = 400):
    return httpx.Response(
        200, json={"ok": False, "error_code": code, "description": description}
    )


# ─────────────────────── Client: validation ─────────────────────────────


async def test_client_requires_token():
    with pytest.raises(BotFatherError):
        BotFatherClient("")


async def test_set_name_validates_locally():
    transport = _mock_transport(lambda r: pytest.fail("must not call telegram"))
    async with httpx.AsyncClient(transport=transport) as http:
        client = BotFatherClient("T", http=http)
        with pytest.raises(BotFatherError):
            await client.set_my_name("")
        with pytest.raises(BotFatherError):
            await client.set_my_name("x" * 65)


async def test_set_short_description_length_limit():
    transport = _mock_transport(lambda r: pytest.fail("must not call telegram"))
    async with httpx.AsyncClient(transport=transport) as http:
        client = BotFatherClient("T", http=http)
        with pytest.raises(BotFatherError):
            await client.set_my_short_description("x" * 121)


async def test_set_commands_rejects_invalid_names():
    transport = _mock_transport(lambda r: pytest.fail("must not call telegram"))
    async with httpx.AsyncClient(transport=transport) as http:
        client = BotFatherClient("T", http=http)
        with pytest.raises(BotFatherError):
            await client.set_my_commands([{"command": "Bad-Name", "description": "x"}])
        with pytest.raises(BotFatherError):
            await client.set_my_commands(
                [
                    {"command": "start", "description": "a"},
                    {"command": "start", "description": "b"},
                ]
            )


# ─────────────────────── Client: HTTP behaviour ─────────────────────────


async def test_client_posts_to_correct_endpoint():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return _ok(True)

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
        client = BotFatherClient("123:ABC", http=http)
        assert await client.set_my_name("Hello") is True
    assert seen["url"].endswith("/bot123:ABC/setMyName")
    assert seen["body"] == {"name": "Hello"}


async def test_client_set_commands_serializes_payload():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _ok(True)

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
        client = BotFatherClient("T", http=http)
        await client.set_my_commands(
            [
                BotCommand(command="start", description="Begin"),
                {"command": "help", "description": "Show help"},
            ]
        )
    assert seen["body"]["commands"] == [
        {"command": "start", "description": "Begin"},
        {"command": "help", "description": "Show help"},
    ]


async def test_client_get_my_commands_returns_typed():
    def handler(_):
        return _ok([{"command": "start", "description": "Begin"}])

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
        client = BotFatherClient("T", http=http)
        cmds = await client.get_my_commands()
    assert cmds == [BotCommand(command="start", description="Begin")]


async def test_client_raises_on_telegram_error():
    def handler(_):
        return _err("Bad Request: name is too long", code=400)

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
        client = BotFatherClient("T", http=http)
        with pytest.raises(BotFatherError) as ei:
            await client.set_my_name("ValidName")
    assert ei.value.code == 400
    assert "too long" in str(ei.value)


async def test_client_raises_on_network_error():
    def handler(_):
        raise httpx.ConnectError("boom")

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
        client = BotFatherClient("T", http=http)
        with pytest.raises(BotFatherError):
            await client.get_me()


# ─────────────────────── Service: ownership ─────────────────────────────


async def test_fetch_profile_rejects_other_users(db_session, seeded_bot):
    with pytest.raises(BotFatherError) as ei:
        await fetch_bot_profile(db_session, "intruder", "b1")
    assert ei.value.code == 403


async def test_fetch_profile_rejects_unknown_bot(db_session, seeded_bot):
    with pytest.raises(BotFatherError) as ei:
        await fetch_bot_profile(db_session, "u1", "ghost")
    assert ei.value.code == 404


# ─────────────────────── Service: happy path ────────────────────────────


def _profile_handler() -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rsplit("/", 1)[-1]
        if path == "getMe":
            return _ok({"id": 99, "username": "fake_bot", "first_name": "Fake"})
        if path == "getMyName":
            return _ok({"name": "Live Name"})
        if path == "getMyDescription":
            return _ok({"description": "long desc"})
        if path == "getMyShortDescription":
            return _ok({"short_description": "short"})
        if path == "getMyCommands":
            return _ok([{"command": "start", "description": "Begin"}])
        return _ok(True)

    return handler


async def test_fetch_profile_happy_path(db_session, seeded_bot):
    async with httpx.AsyncClient(transport=_mock_transport(_profile_handler())) as http:
        profile = await fetch_bot_profile(db_session, "u1", "b1", http=http)
    assert profile.username == "fake_bot"
    assert profile.name == "Live Name"
    assert profile.short_description == "short"
    assert profile.commands[0].command == "start"
    # Audit row written
    rows = (await db_session.execute(select(BotFatherOperation))).scalars().all()
    assert len(rows) == 1
    assert rows[0].op_type == "fetch_profile"
    assert rows[0].success is True


async def test_update_profile_partial_writes_audit(db_session, seeded_bot):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path.rsplit("/", 1)[-1])
        return _ok(True)

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
        results = await update_bot_profile(
            db_session,
            "u1",
            "b1",
            name="New Name",
            short_description="New about",
            http=http,
        )
    # Only the two fields we passed
    assert results == {"name": "ok", "short_description": "ok"}
    assert calls == ["setMyName", "setMyShortDescription"]
    # Local Bot.name mirrored
    bot = await db_session.get(Bot, "b1")
    assert bot.name == "New Name"
    # Two audit rows
    rows = (
        await db_session.execute(
            select(BotFatherOperation).order_by(BotFatherOperation.id)
        )
    ).scalars().all()
    assert [r.op_type for r in rows] == ["set_name", "set_short_description"]
    assert all(r.success for r in rows)


async def test_update_profile_records_per_field_failures(db_session, seeded_bot):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rsplit("/", 1)[-1]
        if path == "setMyDescription":
            return _err("Bad Request: description too long", code=400)
        return _ok(True)

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
        results = await update_bot_profile(
            db_session,
            "u1",
            "b1",
            name="Fine",
            description="anything",
            http=http,
        )
    assert results["name"] == "ok"
    assert results["description"].startswith("failed:")
    rows = (
        await db_session.execute(select(BotFatherOperation))
    ).scalars().all()
    success = {r.op_type: r.success for r in rows}
    assert success == {"set_name": True, "set_description": False}


async def test_update_profile_with_commands(db_session, seeded_bot):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rsplit("/", 1)[-1]
        if path == "setMyCommands":
            seen["commands"] = json.loads(request.content)["commands"]
        return _ok(True)

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
        results = await update_bot_profile(
            db_session,
            "u1",
            "b1",
            commands=[BotCommand(command="start", description="Begin")],
            http=http,
        )
    assert results == {"commands": "ok"}
    assert seen["commands"] == [{"command": "start", "description": "Begin"}]
