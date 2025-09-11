import os
from aiohttp import web


async def handle(_):
    return web.Response(text="Spectre online")


async def start_keepalive():
    app = web.Application()
    app.add_routes([web.get("/", handle), web.get("/health", handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8080")))
    await site.start()
    return runner
