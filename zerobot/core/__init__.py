"""Core platform plumbing.

Modules
-------
delivery         Forward Telegram updates to a bot's local webhook port.
gateway          Public FastAPI service that receives Telegram updates.
limiter          Per-bot token-bucket rate limiter.
orchestrator     Plant / wake / reap bots end-to-end (DB + venv + process).
runtime_manager  Start and stop the underlying bot processes.
wake_buffer      In-memory queue of updates received while a bot is hibernating.
"""
