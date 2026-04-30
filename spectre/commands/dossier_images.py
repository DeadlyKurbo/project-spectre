"""Slash commands related to dossier file management."""

from __future__ import annotations

import nextcord

from async_utils import run_blocking
from dossier import attach_dossier_audio, attach_dossier_image, list_items_recursive
from utils import list_categories

from ..context import SpectreContext
from ..interactions import guild_id_from_interaction


def _autocomplete_items(category: str | None, partial: str, guild_id: int | None = None) -> list[str]:
    if not category:
        return []
    try:
        try:
            items = list_items_recursive(category, max_items=25, guild_id=guild_id)
        except TypeError:
            items = list_items_recursive(category, max_items=25)
    except FileNotFoundError:
        return []
    partial = (partial or "").lower()
    return [item for item in items if item.lower().startswith(partial)][:25]


async def set_file_image_command(
    context: SpectreContext,
    interaction: nextcord.Interaction,
    category: str,
    item: str,
    image: nextcord.Attachment,
    page: int = 1,
) -> None:
    from archivist import _is_archivist  # Local import to avoid circular dependency

    gid = guild_id_from_interaction(interaction)
    if not _is_archivist(interaction.user, guild_id=gid):
        return await interaction.response.send_message(" Archivist only.", ephemeral=True)
    if image.content_type and not image.content_type.startswith("image/"):
        return await interaction.response.send_message(
            " Attachment must be an image.", ephemeral=True
        )
    await interaction.response.defer(ephemeral=True)
    try:
        await run_blocking(attach_dossier_image, category, item, page, image.url, gid)
    except FileNotFoundError:
        return await interaction.followup.send(" File not found.", ephemeral=True)
    except IndexError:
        return await interaction.followup.send(
            " Invalid page number.", ephemeral=True
        )
    await interaction.followup.send(" Image attached.", ephemeral=True)
    await context.log_action(
        f" {interaction.user.mention} attached IMAGE `{category}/{item}` page {page}.",
        guild_id=gid,
    )


async def set_file_audio_command(
    context: SpectreContext,
    interaction: nextcord.Interaction,
    category: str,
    item: str,
    audio: nextcord.Attachment,
    page: int = 1,
) -> None:
    from archivist import _is_archivist  # Local import to avoid circular dependency

    gid = guild_id_from_interaction(interaction)
    if not _is_archivist(interaction.user, guild_id=gid):
        return await interaction.response.send_message(" Archivist only.", ephemeral=True)
    if audio.content_type and not audio.content_type.startswith("audio/"):
        return await interaction.response.send_message(
            " Attachment must be an audio file.", ephemeral=True
        )
    await interaction.response.defer(ephemeral=True)
    try:
        playable_audio_url = audio.proxy_url or audio.url
        await run_blocking(attach_dossier_audio, category, item, page, playable_audio_url, gid)
    except FileNotFoundError:
        return await interaction.followup.send(" File not found.", ephemeral=True)
    except IndexError:
        return await interaction.followup.send(
            " Invalid page number.", ephemeral=True
        )
    await interaction.followup.send(" Audio attached.", ephemeral=True)
    await context.log_action(
        f" {interaction.user.mention} attached AUDIO `{category}/{item}` page {page}.",
        guild_id=gid,
    )


async def set_file_image_item_autocomplete(
    context: SpectreContext, interaction: nextcord.Interaction, item: str
) -> None:
    category = None
    options = interaction.data.get("options", []) if interaction.data else []
    for opt in options:
        if opt.get("name") == "category":
            category = opt.get("value")
            break
    gid = guild_id_from_interaction(interaction)
    choices = await run_blocking(_autocomplete_items, category, item, gid)
    await interaction.response.send_autocomplete(choices)


def register(context: SpectreContext) -> None:
    bot = context.bot

    @bot.slash_command(
        name="set-file-image",
        description="Attach an image to a dossier page",
        guild_ids=context.slash_guild_ids,
    )
    async def set_file_image(
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            name="category",
            description="Dossier category",
            choices={c: c for c in list_categories()[:25]},
        ),
        item: str = nextcord.SlashOption(
            name="item",
            description="Dossier file",
            autocomplete=True,
        ),
        image: nextcord.Attachment = nextcord.SlashOption(
            name="image",
            description="Image to attach",
        ),
        page: int = 1,
    ) -> None:
        await set_file_image_command(context, interaction, category, item, image, page)

    @set_file_image.on_autocomplete("item")
    async def _handler(interaction: nextcord.Interaction, item: str) -> None:
        await set_file_image_item_autocomplete(context, interaction, item)


    @bot.slash_command(
        name="set-file-audio",
        description="Attach an audio file to a dossier page",
        guild_ids=context.slash_guild_ids,
    )
    async def set_file_audio(
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            name="category",
            description="Dossier category",
            choices={c: c for c in list_categories()[:25]},
        ),
        item: str = nextcord.SlashOption(
            name="item",
            description="Dossier file",
            autocomplete=True,
        ),
        audio: nextcord.Attachment = nextcord.SlashOption(
            name="audio",
            description="Audio to attach",
        ),
        page: int = 1,
    ) -> None:
        await set_file_audio_command(context, interaction, category, item, audio, page)

    @set_file_audio.on_autocomplete("item")
    async def _audio_handler(interaction: nextcord.Interaction, item: str) -> None:
        await set_file_image_item_autocomplete(context, interaction, item)


__all__ = [
    "register",
    "set_file_image_command",
    "set_file_image_item_autocomplete",
    "set_file_audio_command",
    "_autocomplete_items",
]
