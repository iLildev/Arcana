"""Background watchdog that hibernates bots after a period of inactivity."""

import asyncio
import time
from collections import defaultdict


class Hibernator:
    """Track last-seen timestamps and reap bots that have been idle too long."""

    def __init__(self, timeout: int = 1800) -> None:
        self.timeout = timeout
        self.last_seen: dict[str, float] = defaultdict(time.time)

    def touch(self, bot_id: str) -> None:
        """Record activity for *bot_id*; resets its idle timer."""
        self.last_seen[bot_id] = time.time()

    def is_idle(self, bot_id: str) -> bool:
        """Return ``True`` if *bot_id* has been silent for longer than ``timeout``."""
        return (time.time() - self.last_seen[bot_id]) > self.timeout

    async def monitor(self, orchestrator) -> None:
        """Run forever, reaping idle bots through *orchestrator* every 30s."""
        while True:
            for bot_id in list(self.last_seen.keys()):
                if self.is_idle(bot_id):
                    await orchestrator.reap_bot(bot_id)
            await asyncio.sleep(30)
