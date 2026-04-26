"""Per-bot in-memory token-bucket rate limiter."""

import time


class RateLimiter:
    """Allow up to *rate* events per second per bot, smoothed by token refill."""

    def __init__(self, rate: int = 5) -> None:
        self.rate = rate
        self.tokens: dict[str, float] = {}
        self.last: dict[str, float] = {}

    def allow(self, bot_id: str) -> bool:
        """Return ``True`` and consume one token, or ``False`` if drained."""
        now = time.time()

        tokens = self.tokens.get(bot_id, self.rate)
        last = self.last.get(bot_id, now)

        delta = now - last
        tokens = min(self.rate, tokens + delta * self.rate)

        if tokens < 1:
            self.tokens[bot_id] = tokens
            self.last[bot_id] = now
            return False

        self.tokens[bot_id] = tokens - 1
        self.last[bot_id] = now
        return True
