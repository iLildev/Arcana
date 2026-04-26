"""Per-bot message counter used by the gateway and ``/stats`` Telegram command."""

import time
from collections import defaultdict


class Tracker:
    """Count messages per bot and render a tiny ASCII status report."""

    def __init__(self) -> None:
        self.messages: dict[str, int] = defaultdict(int)
        self.started_at = time.time()

    def track(self, bot_id: str) -> None:
        """Record one message handled by *bot_id*."""
        self.messages[bot_id] += 1

    def report(self, bot_id: str) -> str:
        """Return a small human-readable status block for *bot_id*."""
        count = self.messages.get(bot_id, 0)
        uptime = int(time.time() - self.started_at)

        bar = "█" * (count % 10) + "░" * (10 - (count % 10))

        return (
            f"📊 Bot Stats\n"
            f"Messages: {count}\n"
            f"Uptime: {uptime}s\n"
            f"Load: [{bar}]\n"
            f"\nPowered by @iLildev"
        )
