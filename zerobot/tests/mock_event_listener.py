"""Tiny mock subscriber for testing the event publisher pipeline.

Listens on ``MOCK_PORT`` (default 8765) and exposes:

* ``POST /events``   — record every event payload.
* ``GET  /received`` — dump all events received so far.
"""

import asyncio
import os

from aiohttp import web

received: list[dict] = []


async def on_event(request: web.Request) -> web.Response:
    """Append the incoming event to the in-memory ``received`` list."""
    body = await request.json()
    received.append(body)
    print(f"📬 received: {body}")
    return web.json_response({"ok": True})


async def dump(request: web.Request) -> web.Response:
    """Return everything received so far as JSON."""
    return web.json_response(received)


async def main() -> None:
    """Run the mock subscriber until interrupted."""
    app = web.Application()
    app.router.add_post("/events", on_event)
    app.router.add_get("/received", dump)

    port = int(os.getenv("MOCK_PORT", "8765"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    print(f"🎧 mock listener on http://127.0.0.1:{port}")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
