"""In-memory queue for updates received while a bot is hibernating.

A single process-wide ``WakeBuffer`` instance (``wake_buffer``) is shared by
the gateway. Updates queued via :py:meth:`WakeBuffer.add` are flushed in FIFO
order by :py:meth:`WakeBuffer.flush` once the bot is awake again.
"""

from collections import defaultdict


class WakeBuffer:
    """Tiny per-bot FIFO that holds updates until the bot is woken up."""

    def __init__(self) -> None:
        self.buffer: dict[str, list[dict]] = defaultdict(list)

    async def add(self, bot_id: str, update: dict) -> None:
        """Append *update* to the queue for *bot_id*."""
        self.buffer[bot_id].append(update)

    async def flush(self, bot_id: str) -> list[dict]:
        """Return and clear every queued update for *bot_id*."""
        updates = self.buffer.pop(bot_id, [])
        return list(updates)


# Process-wide singleton — both the gateway and the orchestrator import this.
wake_buffer = WakeBuffer()
