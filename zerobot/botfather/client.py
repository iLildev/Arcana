"""Async wrapper around the self-management subset of the Telegram Bot API.

Every method here corresponds to a Bot API endpoint that does **not**
require BotFather and **can** be called with a bot token — the same
operations a user would do through ``/mybots`` in BotFather, minus the
photo/deletion ones (those need an MTProto user session).

Telegram limits enforced server-side (we re-validate locally so we can
fail fast without spending a network round-trip):

- ``name``: 1..64 chars
- ``description`` (long): up to 512 chars
- ``short_description`` (about): up to 120 chars
- ``commands``: list of ``{command, description}`` dicts; ≤100 entries,
  command ``[a-z0-9_]{1..32}``, description 1..256 chars.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

# ── Local validation (Telegram's published limits) ───────────────────────

NAME_MAX = 64
DESCRIPTION_MAX = 512
SHORT_DESCRIPTION_MAX = 120
COMMANDS_MAX = 100
COMMAND_NAME_MAX = 32
COMMAND_DESC_MAX = 256
COMMAND_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class BotFatherError(Exception):
    """Raised on any API error (4xx, 5xx, ``ok: false``, or local validation)."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BotCommand:
    """One slash-command entry (``/start — Start the bot``)."""

    command: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {"command": self.command, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BotCommand:
        return cls(command=str(d["command"]), description=str(d["description"]))


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise BotFatherError("name must be a non-empty string")
    if len(name) > NAME_MAX:
        raise BotFatherError(f"name exceeds {NAME_MAX} characters")
    return name


def _validate_description(description: str, *, limit: int, label: str) -> str:
    if not isinstance(description, str):
        raise BotFatherError(f"{label} must be a string")
    if len(description) > limit:
        raise BotFatherError(f"{label} exceeds {limit} characters")
    return description


def _validate_commands(commands: list[BotCommand | dict]) -> list[dict]:
    if len(commands) > COMMANDS_MAX:
        raise BotFatherError(f"too many commands (max {COMMANDS_MAX})")
    out: list[dict] = []
    seen: set[str] = set()
    for item in commands:
        cmd = item if isinstance(item, BotCommand) else BotCommand.from_dict(item)
        if not COMMAND_NAME_RE.match(cmd.command):
            raise BotFatherError(
                f"invalid command name {cmd.command!r}: "
                "must start with a-z and contain only a-z/0-9/_"
            )
        if cmd.command in seen:
            raise BotFatherError(f"duplicate command {cmd.command!r}")
        seen.add(cmd.command)
        if not cmd.description.strip():
            raise BotFatherError(f"command {cmd.command!r} needs a non-empty description")
        if len(cmd.description) > COMMAND_DESC_MAX:
            raise BotFatherError(
                f"command {cmd.command!r} description exceeds {COMMAND_DESC_MAX} chars"
            )
        out.append(cmd.to_dict())
    return out


# ── HTTP client ──────────────────────────────────────────────────────────


class BotFatherClient:
    """Thin async client for the self-management Bot API endpoints.

    Pass ``http=`` to inject your own ``httpx.AsyncClient`` (used by the
    test suite to mock the Telegram backend). Otherwise, use the client
    as an async context manager so the underlying HTTP client is closed
    deterministically.
    """

    BASE_URL = "https://api.telegram.org"

    def __init__(
        self,
        token: str,
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        if not token or not isinstance(token, str):
            raise BotFatherError("token is required")
        self._token = token
        self._http = http
        self._owns_http = http is None
        self._timeout = timeout

    # ── lifecycle ──────────────────────────────────────────────────────

    async def __aenter__(self) -> BotFatherClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
            self._owns_http = True
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # ── transport ──────────────────────────────────────────────────────

    async def _call(self, method: str, **payload: Any) -> Any:
        """Invoke a Telegram Bot API method via JSON POST."""
        if self._http is None:
            # User called us without `async with`; create an ephemeral client.
            self._http = httpx.AsyncClient(timeout=self._timeout)
            self._owns_http = True

        url = f"{self.BASE_URL}/bot{self._token}/{method}"
        body = {k: v for k, v in payload.items() if v is not None and v != ""}
        try:
            resp = await self._http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise BotFatherError(f"network error talking to Telegram: {exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise BotFatherError(f"non-JSON reply from Telegram: {resp.text[:200]}") from exc

        if not data.get("ok"):
            raise BotFatherError(
                data.get("description", "Telegram returned ok=false"),
                code=data.get("error_code"),
            )
        return data["result"]

    # ── identity / introspection ───────────────────────────────────────

    async def get_me(self) -> dict:
        """Return the bot's identity (``username``, ``first_name``, ``id`` …)."""
        return await self._call("getMe")

    # ── name ───────────────────────────────────────────────────────────

    async def get_my_name(self, language_code: str = "") -> str:
        result = await self._call("getMyName", language_code=language_code)
        return str(result.get("name", ""))

    async def set_my_name(self, name: str, language_code: str = "") -> bool:
        _validate_name(name)
        return bool(await self._call("setMyName", name=name, language_code=language_code))

    # ── description (long) ─────────────────────────────────────────────

    async def get_my_description(self, language_code: str = "") -> str:
        result = await self._call("getMyDescription", language_code=language_code)
        return str(result.get("description", ""))

    async def set_my_description(
        self, description: str, language_code: str = ""
    ) -> bool:
        _validate_description(description, limit=DESCRIPTION_MAX, label="description")
        return bool(
            await self._call(
                "setMyDescription",
                description=description,
                language_code=language_code,
            )
        )

    # ── short description (about) ──────────────────────────────────────

    async def get_my_short_description(self, language_code: str = "") -> str:
        result = await self._call("getMyShortDescription", language_code=language_code)
        return str(result.get("short_description", ""))

    async def set_my_short_description(
        self, short_description: str, language_code: str = ""
    ) -> bool:
        _validate_description(
            short_description, limit=SHORT_DESCRIPTION_MAX, label="short_description"
        )
        return bool(
            await self._call(
                "setMyShortDescription",
                short_description=short_description,
                language_code=language_code,
            )
        )

    # ── commands ───────────────────────────────────────────────────────

    async def get_my_commands(self, language_code: str = "") -> list[BotCommand]:
        result = await self._call("getMyCommands", language_code=language_code)
        return [BotCommand.from_dict(item) for item in (result or [])]

    async def set_my_commands(
        self,
        commands: list[BotCommand | dict],
        language_code: str = "",
    ) -> bool:
        validated = _validate_commands(commands)
        return bool(
            await self._call(
                "setMyCommands",
                commands=validated,
                language_code=language_code,
            )
        )

    async def delete_my_commands(self, language_code: str = "") -> bool:
        return bool(await self._call("deleteMyCommands", language_code=language_code))
