"""Helpers for displaying archive status and changelog information."""

from datetime import datetime, UTC
import nextcord
from nextcord import Embed
from nextcord.ext import commands

from constants import MENU_CHANNEL_ID, ROOT_PREFIX, ARCHIVE_COLOR
from config import (
    get_build_version,
    get_latest_changelog,
    get_status_message_id,
    get_system_health,
    set_status_message_id,
)
from storage_spaces import list_dir


def _count_all_files(prefix: str) -> int:
    """Recursively count all files under ``prefix``.

    This mirrors the logic used in :mod:`main` but is kept independent so the
    status helpers can be imported without triggering other side effects.
    """

    total = 0
    stack = [prefix]
    seen = set()
    while stack:
        base = stack.pop()
        if base in seen:
            continue
        seen.add(base)
        try:
            dirs, files = list_dir(base, limit=10000)
        except Exception:
            continue
        total += len([f for f, _ in files if not f.endswith(".keep")])
        for d in dirs:
            stack.append(f"{base}/{d.strip('/')}")
    return total


def build_status_embed(
    total_files: int,
    version: str,
    latency_ms: int,
    changelog: dict | None,
    health: str,
) -> Embed:
    """Return a status embed reflecting the current archive state."""

    lines = [
        f"📁 Total Files: {total_files}",
        f"⚙️ Current Bot Version: {version}",
        f"📶 Latency / Ping: {latency_ms} ms",
        "",
        "📝 Latest Changelog",
    ]
    if changelog:
        ts = changelog.get("timestamp")
        update = changelog.get("update", "")
        notes = changelog.get("notes", "")
        lines.append(f"[{ts}]") if ts else None
        if update:
            lines.append(f"Update: {update}")
        if notes:
            lines.append(f"Notes: {notes}")
    else:
        lines.append("No updates logged")
    lines.extend(["", f"💻 System Health: {health}"])
    desc = "\n".join(lines)
    return Embed(title="📡 Archive System Status", description=desc, color=ARCHIVE_COLOR)


async def update_status_message(bot: commands.Bot) -> None:
    """Create or update the archive status message in the configured channel."""

    channel = bot.get_channel(MENU_CHANNEL_ID)
    if not channel or channel.type != nextcord.ChannelType.text:
        return

    total_files = _count_all_files(ROOT_PREFIX)
    version = get_build_version()
    latency_ms = int(bot.latency * 1000)
    changelog = get_latest_changelog()
    health = get_system_health()
    embed = build_status_embed(total_files, version, latency_ms, changelog, health)

    msg_id = get_status_message_id()
    try:
        if msg_id:
            try:
                message = await channel.fetch_message(msg_id)
                await message.edit(embed=embed)
                return
            except Exception:
                pass
        message = await channel.send(embed=embed)
        set_status_message_id(message.id)
    except Exception:
        # Silently ignore failures to avoid crashing the bot if permissions or
        # network issues prevent sending the status message.
        pass


async def record_changelog(update: str, notes: str = "") -> None:
    """Record a new changelog entry and refresh the status message."""

    entry = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "update": update,
        "notes": notes,
    }
    from config import set_latest_changelog  # local import to avoid cycle

    set_latest_changelog(entry)
    # ``bot`` cannot be imported here without risking circular imports; callers
    # are expected to invoke :func:`update_status_message` separately after
    # recording a changelog entry.
