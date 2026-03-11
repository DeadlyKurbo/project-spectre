"""Slash commands for interacting with the Archivist console."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Mapping

import nextcord
from nextcord import Embed

import archivist
import constants as _constants_module
from constants import (
    HIGH_COMMAND_DESC,
    HIGH_COMMAND_TITLE,
    LEAD_ARCHIVIST_DESC,
    LEAD_ARCHIVIST_TITLE,
    REG_ARCHIVIST_DESC,
    REG_ARCHIVIST_TITLE,
    TRAINEE_ARCHIVIST_DESC,
    TRAINEE_ARCHIVIST_TITLE,
)
from server_config import get_server_config

from ..context import SpectreContext
from ..interactions import guild_id_from_interaction


_active_context: SpectreContext | None = None


def _config_lookup(config: Mapping | object | None, key: str, default=None):
    if config is None:
        return default
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            return getter(key, default)  # type: ignore[misc]
        except TypeError:
            return getter(key)
    if isinstance(config, Mapping):
        return config.get(key, default)
    return default


def _clean_console_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _console_copy(
    config: Mapping | object | None,
    entry_key: str,
    fallback_title: str,
    fallback_desc: str,
) -> tuple[str, str]:
    archive_cfg = _config_lookup(config, "archive")
    if not isinstance(archive_cfg, Mapping):
        archive_cfg = {}
    consoles = archive_cfg.get("consoles") if isinstance(archive_cfg, Mapping) else None
    entry = consoles.get(entry_key) if isinstance(consoles, Mapping) else None
    if not isinstance(entry, Mapping):
        entry = {}
    title = _clean_console_text(entry.get("title"))
    desc = _clean_console_text(entry.get("description"))
    return title or fallback_title, desc or fallback_desc


async def maybe_simulate_hiccup(context: SpectreContext, interaction: nextcord.Interaction) -> bool:
    if random.random() < context.settings.hiccup_chance:
        await interaction.response.send_message(
            " Node ECHO-04 failed to respond, rerouting… please hold.",
            ephemeral=True,
        )
        await asyncio.sleep(random.randint(3, 5))
        await interaction.edit_original_message(
            content=" Node ECHO-04 failed to respond, rerouting… please hold. Connection restored."
        )
        await context.log_action(
            " Node ECHO-04 failed to respond, rerouting… please hold. Connection restored."
        )
        return True
    return False


async def open_archivist_console(
    context: SpectreContext, interaction: nextcord.Interaction
) -> None:
    if not archivist._is_archivist(interaction.user):
        return await interaction.response.send_message(" Archivist only.", ephemeral=True)
    sender = interaction.response.send_message
    if await maybe_simulate_hiccup(context, interaction):
        sender = interaction.followup.send
    is_high = archivist._is_high_command(interaction.user)
    gid = guild_id_from_interaction(interaction)
    if archivist.is_archive_locked(gid) and not is_high:
        return await sender(" Archive access locked.", ephemeral=True)
    is_lead = is_high or archivist._is_lead_archivist(interaction.user)
    user_roles = {r.id for r in interaction.user.roles}
    trainee_role_id = getattr(_constants_module, "TRAINEE_ROLE_ID", 0)
    archivist_role_id = getattr(_constants_module, "ARCHIVIST_ROLE_ID", 0)
    is_trainee = (
        trainee_role_id in user_roles
        and not is_lead
        and archivist_role_id not in user_roles
    )
    cfg = get_server_config(gid or 0)
    view = (
        archivist.ArchivistConsoleView(interaction.user, guild_id=gid)
        if is_lead
        else archivist.ArchivistTraineeConsoleView(interaction.user, guild_id=gid)
        if is_trainee
        else archivist.ArchivistLimitedConsoleView(interaction.user, guild_id=gid)
    )
    if is_high:
        title, description = _console_copy(
            cfg, "high_command", HIGH_COMMAND_TITLE, HIGH_COMMAND_DESC
        )
        embed = Embed(title=title, description=description, color=0xFF0000)
    elif is_lead:
        title, description = _console_copy(
            cfg, "lead", LEAD_ARCHIVIST_TITLE, LEAD_ARCHIVIST_DESC
        )
        embed = Embed(title=title, description=description, color=0x3C2E7D)
    elif is_trainee:
        title, description = _console_copy(
            cfg, "trainee", TRAINEE_ARCHIVIST_TITLE, TRAINEE_ARCHIVIST_DESC
        )
        embed = Embed(title=title, description=description, color=0x00FFCC)
    else:
        title, description = _console_copy(
            cfg, "regular", REG_ARCHIVIST_TITLE, REG_ARCHIVIST_DESC
        )
        embed = Embed(title=title, description=description, color=0x0FA3B1)
    await sender(embed=embed, view=view, ephemeral=True)


async def dispatch_archivist_console(interaction: nextcord.Interaction) -> None:
    """Open the Archivist console for ``interaction``.

    Slash commands receive the :class:`SpectreContext` when they register but
    button interactions originating from :class:`views.RootView` do not.  To
    bridge the two entry points we store the most recent context at register
    time and reuse it here.  When the context is unavailable we fail
    gracefully instead of throwing an exception in the interaction handler.
    """

    context = _active_context
    if context is None:
        responder = getattr(interaction, "response", None)
        send_message = getattr(responder, "send_message", None)
        if callable(send_message):
            await send_message(
                " Archivist console temporarily unavailable. Please try again.",
                ephemeral=True,
            )
        else:  # pragma: no cover - defensive fallback for unexpected stubs
            followup = getattr(interaction, "followup", None)
            if followup is not None:
                await followup.send(
                    " Archivist console temporarily unavailable. Please try again.",
                    ephemeral=True,
                )
        return

    await open_archivist_console(context, interaction)


def register(context: SpectreContext) -> None:
    bot = context.bot

    global _active_context
    _active_context = context

    @bot.slash_command(
        name="archivist",
        description="Open the Archivist Console",
        guild_ids=context.slash_guild_ids,
    )
    async def archivist_cmd(interaction: nextcord.Interaction) -> None:
        await dispatch_archivist_console(interaction)


__all__ = [
    "register",
    "maybe_simulate_hiccup",
    "open_archivist_console",
    "dispatch_archivist_console",
]
