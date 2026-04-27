# Workspace

## Overview

This workspace hosts **ZeroBot** — a Python multi-tenant Telegram bot platform
with hibernating runtimes, wallet billing in "crystals", and an autonomous
coding agent (Builder Agent) powered by Claude. See `README.md` for the full
product description and `CONTRIBUTING.md` for the contributor guide.

## Stack

- **Language**: Python 3.11+
- **Web framework**: FastAPI (gateway, admin console, user console)
- **Telegram**: aiogram 3 (Builder Bot, Manager Bot)
- **AI**: Anthropic Claude via Replit AI Integrations
- **Database**: PostgreSQL + SQLAlchemy 2.0 (async, asyncpg driver)
- **Lint / format**: Ruff
- **Build backend**: Hatchling

## Project layout

```
zerobot/             — main Python package (see README.md for module map)
LICENSE              — MIT
README.md            — product overview + run instructions
CONTRIBUTING.md      — contributor guide
.env.example         — full set of supported env vars
pyproject.toml       — project metadata + ruff config
```

## Key commands

- `make install` (or `pip install -e ".[dev]"`) — install runtime + dev deps
- `make check` — run lint + format-check + tests (the CI gate)
- `make test` (or `pytest`) — run the test suite (`tests/` at the repo root)
- `python -m zerobot.main` — bootstrap DB, run additive migrations, seed ports
- `python -m zerobot.agents.cli_test` — interactive Builder Agent REPL
- `ruff check zerobot tests` — lint the codebase
- `ruff format zerobot tests` — auto-format the codebase
- `docker compose up --build` — bring up the full stack (Postgres + 5 services)
- `pre-commit install` — wire up the auto-formatting git hook

### Running the services

Each service is a separate process. See the **Quick start** section of
`README.md` for the exact `uvicorn` / `python -m` invocations.

| Service | Module | Default port |
|---------|--------|--------------|
| Gateway | `zerobot.core.gateway:app` | 8001 |
| User Console | `zerobot.api.user_console:app` | 8000 |
| Admin Console | `zerobot.api.admin_console:app` | 8002 |
| Builder Bot | `zerobot.bots.builder_bot.main` | (Telegram polling) |
| Manager Bot | `zerobot.bots.manager_bot.main` | 8003 (events) + Telegram polling |

## Configuration

All runtime configuration is read from environment variables (or a `.env`
file at the project root). See `.env.example` for the full list of keys
and their descriptions. Secrets that must never be committed:

- `ADMIN_TOKEN`
- `BUILDER_BOT_TOKEN`, `MANAGER_BOT_TOKEN`
- `AI_INTEGRATIONS_ANTHROPIC_*`
- `MASTER_ENCRYPTION_KEY`, `PHONE_HMAC_KEY` (Phase 0 identity layer)
- `DATABASE_URL` (when it contains a real password)

## Phase 0 — Identity layer (built April 2026)

The platform now enforces a Telegram phone-verification gate before any
bot is created or any Builder Agent turn is run (admins are exempt; can
be globally disabled via `REQUIRE_PHONE_VERIFICATION=false` for tests).

- **`zerobot/security/`** — versioned AES-GCM envelopes (with AAD) and
  HMAC helpers. Master keys resolved from env, with a deterministic dev
  fallback and loud warning when unset.
- **`zerobot/identity/`** — phone normalization (E.164), HMAC-based dedup,
  bot-quota check (default 3 per phone), and encrypted MTProto session
  storage (substrate for Phase 1 BotFather automation).
- **DB additions** — `User` gained `phone_encrypted` (BYTEA),
  `phone_hash` (unique partial index), `phone_verified_at`, `bot_quota`.
  New tables: `bot_owner_sessions`, `phone_verification_log`,
  `botfather_operations`. Columns added via `ADDITIVE_MIGRATIONS` so
  existing deployments upgrade cleanly.
- **Builder Bot** — `request_contact` keyboard on first use; `/unlink_phone`
  for GDPR-style deletion.
- **User Console** — `POST /users/{id}/bots` returns HTTP 403 with
  `phone_verification_required` or `bot_quota_exceeded` when the gates
  fail.
- **Admin Console + Manager Bot** — `/identity`, `/unverify`,
  `/unlink_session`, `/setquota` admin overrides.

## Phase 1.ج — BotFather automation, Bot API portion (April 2026)

Users can now manage their planted bots' public profile (name,
descriptions, slash-commands) from inside ZeroBot — without ever
opening @BotFather. Photo uploads, token rotation, and bot deletion
ship in a follow-up phase that needs an MTProto user session.

- **`zerobot/botfather/`** — async `BotFatherClient` wrapping the
  Telegram Bot API self-management endpoints (`getMe`,
  `set/getMyName`, `set/getMyDescription`, `set/getMyShortDescription`,
  `set/getMyCommands`, `deleteMyCommands`). Local validation matches
  Telegram's documented limits so we fail fast.
- **Service layer** — `fetch_bot_profile()` and `update_bot_profile()`
  enforce ownership (`bot.user_id == caller`) and write one
  `BotFatherOperation` audit row per attempted op. Partial updates only
  hit the fields the caller passes; per-field failures are reported in
  the response without aborting the rest.
- **User Console API** — `GET /users/{uid}/bots/{bid}/profile` reads
  the live profile; `PATCH /users/{uid}/bots/{bid}/profile` accepts any
  subset of `{name, description, short_description, commands}`. Phone
  gate enforced (admins exempt).
- **Builder Bot** — new commands: `/mybots`, `/profile <bot_id>`,
  `/setname <bot_id> <name>`, `/setdesc <bot_id> <desc>`, `/setabout
  <bot_id> <about>`. All gated on phone verification.
- **Tests** — 15 new tests using `httpx.MockTransport` (no real
  network) cover client validation, transport happy paths, error
  surfacing, ownership enforcement, partial updates, audit logging,
  and per-field failure recording.

## Notes

- The `artifacts/` directory contains an unrelated pnpm/TypeScript template
  that was scaffolded by the workspace; ZeroBot does not depend on it.
- Per-bot virtualenvs and Builder Agent sandbox workspaces live under
  `zerobot/runtime_envs/` and are gitignored (see `.gitignore`).
