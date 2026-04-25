import asyncio

import httpx


class DeliveryManager:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=5.0)

    async def forward(self, port: int, update: dict):
        url = f"http://127.0.0.1:{port}/webhook"

        for attempt in range(3):
            try:
                await self.client.post(url, json=update)
                return
            except Exception:
                await asyncio.sleep(0.3)

        raise RuntimeError("Delivery failed after retries")
