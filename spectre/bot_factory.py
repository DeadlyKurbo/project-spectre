"""Factory helpers for creating the Nextcord bot client."""

from __future__ import annotations

import asyncio

import nextcord
from nextcord.ext import commands


def ensure_event_loop() -> None:
    """Ensure an asyncio event loop exists for the current thread."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def create_bot() -> commands.Bot:
    """Create the Spectre ``commands.Bot`` instance with the required intents."""

    intents = nextcord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.members = True
    return commands.Bot(intents=intents)


__all__ = ["create_bot", "ensure_event_loop"]
