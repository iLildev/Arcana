"""ZeroBot — multi-tenant Telegram bot platform with hibernating runtimes.

ZeroBot lets users plant, manage, and pay for their own Telegram bots from
inside another Telegram bot. The platform handles isolation (per-bot virtual
environment), lifecycle (wake / hibernate based on traffic), wallet-based
billing in "crystals", and an autonomous coding agent (Builder Agent) that
turns natural-language requests into working code.

Top-level subpackages
---------------------
agents       Builder Agent — Claude-driven coding agent + sandbox + tools.
analytics    In-memory traffic counters per bot.
api          FastAPI services (admin console, user console).
bots         Standalone Telegram bots (Builder Bot, Manager Bot).
core         Gateway, orchestrator, rate limiter, runtime + wake buffer.
database     SQLAlchemy async engine, models, wallet + port registry.
events       Fire-and-forget event publisher.
hibernation  Idle-detection + automatic reaping of inactive bots.
isolation    Per-bot virtualenv lifecycle.
templates    Starter templates copied into freshly-planted bots.
tests        Helper scripts used during local development.

The package is laid out so each entry-point (gateway, console, bot) can be
launched independently — see ``README.md`` for run instructions.
"""

__version__ = "0.1.0"
