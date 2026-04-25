import asyncio
from collections import defaultdict


class WakeBuffer:
    def __init__(self):
        self.buffer = defaultdict(list)

    async def add(self, bot_id: str, update: dict):
        self.buffer[bot_id].append(update)

    async def flush(self, bot_id: str):
        updates = self.buffer.pop(bot_id, [])
        return list(updates)


wake_buffer = WakeBuffer()
