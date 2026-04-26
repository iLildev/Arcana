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

- `pip install -e ".[dev]"` — install runtime + dev dependencies (editable)
- `python -m zerobot.main` — bootstrap DB, run additive migrations, seed ports
- `python -m zerobot.agents.cli_test` — interactive Builder Agent REPL
- `ruff check zerobot` — lint the codebase
- `ruff format zerobot` — auto-format the codebase

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
- `DATABASE_URL` (when it contains a real password)

## Notes

- The `artifacts/` directory contains an unrelated pnpm/TypeScript template
  that was scaffolded by the workspace; ZeroBot does not depend on it.
- Per-bot virtualenvs and Builder Agent sandbox workspaces live under
  `zerobot/runtime_envs/` and are gitignored (see `.gitignore`).
