# Workspace

## Overview

This workspace hosts **Arcana** — a Python multi-tenant Telegram bot
platform with hibernating runtimes, wallet billing in "crystals", and
an autonomous coding agent (Builder Agent) powered by Anthropic Claude.

> Renamed from the older codename **ZeroBot** (April 2026). All module
> paths and environment variables now use the `arcana` namespace.

See `README.md` for the full product description and `CONTRIBUTING.md`
for the contributor guide.

## Stack

- **Language**: Python 3.11+ (3.12 supported)
- **Web framework**: FastAPI (gateway, admin console, user console)
- **Telegram**: aiogram 3 (Builder Bot, Manager Bot)
- **AI**: Anthropic Claude via Replit AI Integrations
- **Database**: PostgreSQL 14+ + SQLAlchemy 2.0 (async, asyncpg driver)
- **Tests**: pytest with `aiosqlite` for hermetic in-memory DB
- **Lint / format**: Ruff
- **Build backend**: Hatchling

## Project layout

```
arcana/             — main Python package (see README.md for module map)
tests/              — pytest suite (unit + integration)
LICENSE             — MIT
README.md           — product overview + run instructions
CONTRIBUTING.md     — contributor guide
SECURITY.md         — vulnerability reporting + operator hardening
.env.example        — full set of supported env vars (documented)
pyproject.toml      — project metadata + ruff + pytest config
Makefile            — common dev tasks (install, lint, test, …)
Dockerfile          — single base image used by every service
docker-compose.yml  — full local stack (postgres + 5 services)
```

## Key commands

- `make install` (or `pip install -e ".[dev]"`) — install runtime + dev deps
- `make check` — run lint + format-check + tests (the CI gate)
- `make test` (or `pytest`) — run the test suite (`tests/` at the repo root)
- `python -m arcana.main` — bootstrap DB, run additive migrations, seed ports
- `python -m arcana.agents.cli_test` — interactive Builder Agent REPL
- `ruff check arcana tests` — lint the codebase
- `ruff format arcana tests` — auto-format the codebase
- `docker compose up --build` — bring up the full stack (Postgres + 5 services)
- `pre-commit install` — wire up the auto-formatting git hook

### Running the services

Each service is a separate process. See the **Quick start** section of
`README.md` for the exact `uvicorn` / `python -m` invocations.

| Service       | Module                          | Default port                          |
| ------------- | ------------------------------- | ------------------------------------- |
| Gateway       | `arcana.core.gateway:app`       | 8001                                  |
| User Console  | `arcana.api.user_console:app`   | 8000                                  |
| Admin Console | `arcana.api.admin_console:app`  | 8002                                  |
| Builder Bot   | `arcana.bots.builder_bot.main`  | (Telegram polling)                    |
| Manager Bot   | `arcana.bots.manager_bot.main`  | 8003 (events) + Telegram polling      |

## Configuration

All runtime configuration is read from environment variables (or a
`.env` file at the project root). See `.env.example` for the full list
of keys and their descriptions. Secrets that must **never** be
committed:

- `ADMIN_TOKEN`
- `BUILDER_BOT_TOKEN`, `MANAGER_BOT_TOKEN`
- `AI_INTEGRATIONS_ANTHROPIC_*`
- `MASTER_ENCRYPTION_KEY`, `PHONE_HMAC_KEY` (Phase 0 identity layer)
- `EVENT_SHARED_SECRET` (HMAC signing for fire-and-forget events)
- `DATABASE_URL` (when it contains a real password)

## Phase 0 — Identity layer (built April 2026)

The platform enforces a Telegram phone-verification gate before any
bot is created or any Builder Agent turn is run (admins are exempt;
can be globally disabled via `REQUIRE_PHONE_VERIFICATION=false` for
tests).

- **`arcana/security/`** — versioned AES-GCM envelopes (with AAD) and
  HMAC helpers. Master keys resolved from env, with a deterministic
  dev fallback and loud warning when unset.
- **`arcana/identity/`** — phone normalization (E.164), HMAC-based
  dedup, bot-quota check (default 3 per phone), and encrypted MTProto
  session storage (substrate for Phase 1 BotFather automation).
- **DB additions** — `User` gained `phone_encrypted` (BYTEA),
  `phone_hash` (unique partial index), `phone_verified_at`,
  `bot_quota`. New tables: `bot_owner_sessions`,
  `phone_verification_log`, `botfather_operations`. Columns added via
  `ADDITIVE_MIGRATIONS` so existing deployments upgrade cleanly.
- **Builder Bot** — `request_contact` keyboard on first use;
  `/unlink_phone` for GDPR-style deletion.
- **User Console** — `POST /users/{id}/bots` returns HTTP 403 with
  `phone_verification_required` or `bot_quota_exceeded` when the gates
  fail.
- **Admin Console + Manager Bot** — `/identity`, `/unverify`,
  `/unlink_session`, `/setquota` admin overrides.

## Phase 1.ج — BotFather automation, Bot API portion (April 2026)

Users can manage their planted bots' public profile (name,
descriptions, slash-commands) from inside Arcana — without ever
opening @BotFather. Photo uploads, token rotation, and bot deletion
ship in a follow-up phase that needs an MTProto user session.

- **`arcana/botfather/`** — async `BotFatherClient` wrapping the
  Telegram Bot API self-management endpoints (`getMe`,
  `set/getMyName`, `set/getMyDescription`, `set/getMyShortDescription`,
  `set/getMyCommands`, `deleteMyCommands`). Local validation matches
  Telegram's documented limits so we fail fast.
- **Service layer** — `fetch_bot_profile()` and `update_bot_profile()`
  enforce ownership (`bot.user_id == caller`) and write one
  `BotFatherOperation` audit row per attempted op. Partial updates
  only hit the fields the caller passes; per-field failures are
  reported in the response without aborting the rest.
- **User Console API** — `GET /users/{uid}/bots/{bid}/profile` reads
  the live profile; `PATCH /users/{uid}/bots/{bid}/profile` accepts
  any subset of `{name, description, short_description, commands}`.
  Phone gate enforced (admins exempt).
- **Builder Bot** — new commands: `/mybots`, `/profile <bot_id>`,
  `/setname <bot_id> <name>`, `/setdesc <bot_id> <desc>`,
  `/setabout <bot_id> <about>`. All gated on phone verification.
- **Tests** — 15 tests using `httpx.MockTransport` (no real network)
  cover client validation, transport happy paths, error surfacing,
  ownership enforcement, partial updates, audit logging, and
  per-field failure recording.

## Documentation conventions

- **English** is the default language for code, docstrings, and module
  headers — that's the lingua franca of the Python ecosystem and keeps
  the door open for international contributors.
- **Arabic** is used inline (in dedicated `# ar:` comment blocks) to
  explain *why* a non-obvious design decision was made — the kind of
  thing that would otherwise be lost in a future grep. The convention
  is `# ar: …` so these blocks are easy to find and translate later.

## Notes

- The `artifacts/` directory contains an unrelated pnpm/TypeScript
  template that was scaffolded by the workspace; Arcana itself does
  not depend on it. The workflow `Start application` runs the
  TypeScript artifact for live preview only.
- Per-bot virtualenvs and Builder Agent sandbox workspaces live under
  `arcana/runtime_envs/` and are gitignored (see `.gitignore`).
- The pytest suite passes 157/157 tests against an in-memory SQLite DB
  (no external services required).

## Reusable middleware & services (Wave 1 port from rdfsx/aiogram-template)

After analysing `rdfsx/aiogram-template` we ported only the patterns that
fit Arcana's architecture (skipping its MongoDB/Russian-UI assumptions):

- **`arcana/bots/middleware/`** — bot-agnostic middlewares shared by
  Builder Bot and Manager Bot:
  - `ThrottlingMiddleware` — pure-Python per-(user, handler) sliding-
    window limiter (no `aiolimiter` dep). Handlers can opt into a custom
    rate via `@throttle(seconds)`.
  - `DBSessionMiddleware` — opens an `AsyncSession` per handler call and
    rolls back on uncaught exceptions. Handlers receive the session via
    aiogram DI (`session=` kwarg).
  - `build_error_router(bot_label, apology_text=None)` — global error
    catcher that logs the trace, emits a typed `bot_error` event to the
    Manager Bot's `/events` endpoint, and optionally apologises to the
    user. Returns a `Router` ready to `include_router(...)`.
- **`arcana/services/broadcast.py`** — `broadcast_text(bot, user_ids,
  text, ...)` helper that handles `TelegramRetryAfter` (sleeps + retries
  once), `TelegramForbiddenError` (counts blocked users + invokes
  `on_blocked` hook), and other API errors. Returns a `BroadcastResult`
  dataclass with `sent / blocked / failed / total` counters. Accepts
  both sync iterables and async generators (for streamed DB cursors).

### New events flowing through the platform event bus

- `user_registered` — fired exactly once on first phone-verification.
  Now carries `username`, `full_name`, `language`, `telegram_user_id`
  and a `photo_file_id` (the user's largest available profile photo,
  reusable across bots so the Manager Bot re-sends it via `send_photo`
  with no re-upload).
- `user_blocked_bot` / `user_unblocked_bot` — emitted from the new
  `my_chat_member` handler in Builder Bot, so admins are notified the
  moment a user blocks/un-blocks the bot.
- `bot_error` — emitted by every bot's error router on any un-handled
  exception (carries `bot`, `error`, `user_id`, `update_id`, `trace`).
- `broadcast_completed` — emitted at the end of every `/broadcast`
  with `sent / blocked / failed / total` counts.

### New Builder Bot command

- `/broadcast <message>` — admin-only, throttled at 5s/call. Selects
  every user with `phone_verified_at IS NOT NULL`, sends in parallel
  with the broadcast service, and posts a final summary to the admin.
  Localised in all 6 supported languages (ar / en / fr / es / ru / tr).

### Test coverage added

- `tests/test_throttling_middleware.py` (7 tests) — drop, isolation by
  user/handler, decorator override, no-user pass-through.
- `tests/test_db_session_middleware.py` (3 tests) — session injection,
  commit visibility, rollback-on-exception (uses `aiosqlite`).
- `tests/test_broadcast_service.py` (7 tests) — success, blocked +
  callback, FloodWait retry, generic API errors, progress callback,
  async-iterable input.
