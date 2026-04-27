"""Cross-bot reusable services (broadcasting, batched API calls, …).

Lives outside ``arcana/bots/`` because these helpers are bot-agnostic and
may also be invoked from the FastAPI consoles or CLI tools.
"""
