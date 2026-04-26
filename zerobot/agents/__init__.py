"""Builder Agent — autonomous coding agent core for ZeroBot.

Modules
-------
sandbox        Per-user isolated workspace + safe shell / file operations.
tools          Anthropic tool schemas + dispatcher routed through the sandbox.
llm            Claude client wired through the Replit AI Integrations proxy.
builder_agent  The agent loop (Claude + tools + iteration).
cli_test       Interactive REPL for testing without Telegram.
"""
