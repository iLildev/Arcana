"""Reliable forwarder that posts a Telegram update to a bot's webhook port."""

import asyncio

import httpx


class DeliveryManager:
    """Send updates to ``http://127.0.0.1:{port}/webhook`` with simple retries."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=5.0)

    async def forward(self, port: int, update: dict) -> None:
        """Post *update* to the bot listening on *port*; retry up to 3 times."""
        url = f"http://127.0.0.1:{port}/webhook"

        for _ in range(3):
            try:
                await self.client.post(url, json=update)
                return
            except Exception:
                # Transient: connection reset while a bot is restarting.
                await asyncio.sleep(0.3)

        raise RuntimeError("Delivery failed after retries")
