"""Lazarus AI core.

This module originally only exposed a minimal health monitor.  In order to
make the agent more responsive and give it basic learning capabilities we add
a very small conversational layer.  The goal is not to build a full blown
language model but to provide a deterministic, "cold" interaction style that
logs messages and can surface information from the archive storage.
"""

from datetime import datetime, UTC, timedelta
import re
from typing import List, Dict, Any

import nextcord
from nextcord.ext import commands, tasks

from constants import GUILD_ID, LLM_API_KEY
import llm_client
from storage_spaces import read_text, read_json, save_json

# File within the configured storage where Lazarus persists a minimal memory
LAZARUS_MEMORY_PATH = "lazarus/memory.json"

class LazarusAI(commands.Cog):
    """Minimal hidden AI core monitoring the guild.

    The cog maintains a silent background loop (``shadow_loop``) which checks
    for basic health indicators such as a heartbeat and the age of the most
    recent backup.  Status messages are posted to the designated channel and a
    ``/lazarus status`` command exposes the current health summary on demand.
    Outside of that channel the AI observes all messages but only responds when
    directly addressed by name to remain unobtrusive.
    """

    def __init__(self, bot: commands.Bot, channel_id: int, backup_interval_hours: float, status_interval_minutes: int = 5):
        self.bot = bot
        self.channel_id = channel_id
        self.backup_interval = timedelta(hours=backup_interval_hours)
        self.status_interval_minutes = status_interval_minutes
        self.last_backup_ts = datetime.now(UTC)
        self.last_heartbeat = datetime.now(UTC)
        self.shadow_loop.change_interval(minutes=status_interval_minutes)

        # === conversational state ===
        # A small rolling memory of previous messages.  This gives the agent a
        # hint of "learning" without any heavy ML dependencies.  The memory is
        # stored in the project storage using the ``storage_spaces`` helpers so
        # that test environments as well as production can share the same
        # implementation.
        self.memory: List[Dict[str, Any]] = self._load_memory()

    def start(self) -> None:
        """Start the shadow monitoring loop."""
        if not self.shadow_loop.is_running():
            self.shadow_loop.start()

    def note_backup(self, ts: datetime | None = None) -> None:
        """Record that a backup completed at ``ts`` (or ``now``)."""
        self.last_backup_ts = ts or datetime.now(UTC)

    def compute_status(self, now: datetime | None = None) -> str | None:
        """Return a short human readable health summary.

        The method only returns a message when an issue is detected.  ``None``
        signifies that everything looks healthy and avoids emitting the
        previously noisy "System Check: OK" notification.
        """
        now = now or datetime.now(UTC)
        if now - self.last_heartbeat > timedelta(minutes=self.status_interval_minutes * 2):
            return "Heartbeat stalled"
        if now - self.last_backup_ts > self.backup_interval:
            return "Backup outdated"
        return None

    # ------------------------------------------------------------------
    # Learning helpers
    def _load_memory(self) -> List[Dict[str, Any]]:
        """Load conversation memory from storage.

        Any errors (missing file, corrupt JSON) simply result in an empty
        memory store.  The memory is a list of ``{"ts": ..., "text": ...}``.
        """
        try:
            data = read_json(LAZARUS_MEMORY_PATH)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    def _save_memory(self) -> None:
        """Persist the current memory buffer."""
        try:
            save_json(LAZARUS_MEMORY_PATH, self.memory)
        except Exception:
            # persistence failures should not crash the bot
            pass

    def learn_from(self, text: str) -> None:
        """Record a new observation in memory."""
        entry = {"ts": datetime.now(UTC).isoformat(), "text": text}
        self.memory.append(entry)
        # Keep memory from growing without bound.  50 entries is enough to give
        # the illusion of short term memory while keeping disk usage tiny.
        self.memory = self.memory[-50:]
        self._save_memory()

    def _from_archive(self, path: str) -> str:
        """Retrieve a text snippet from the archive storage."""
        try:
            content = read_text(path).strip()
        except FileNotFoundError:
            return "Archive entry not found."  # cold, factual
        except Exception:
            return "Archive access error."  # do not reveal internals
        # Limit to Discord message size without markdown formatting
        if len(content) > 1800:
            content = content[:1800] + "…"
        return content

    def generate_response(self, prompt: str) -> str:
        """Return a response for ``prompt``.

        The AI favours a deterministic, terse style but will delegate to the
        configured LLM when an API key is present.  LLM failures fall back to
        the deterministic behaviour so tests and offline environments remain
        stable.
        """
        lowered = prompt.strip().lower()
        # Basic archive access: "read path/to/file.txt"
        m = re.match(r"read\s+(.+)", lowered)
        if m:
            path = m.group(1).strip()
            snippet = self._from_archive(path)
            return f"ARCHIVE::{path} -> {snippet}"

        if LLM_API_KEY:
            try:
                return llm_client.complete(prompt)
            except Exception:
                # Any API issues revert to deterministic behaviour
                pass

        # General fallback – acknowledge receipt and mention last memory item
        last = self.memory[-1]["text"] if self.memory else "none"
        return f"ACK: {lowered} | MEMREF: {last}"  # intentionally terse

    @tasks.loop(minutes=1)
    async def shadow_loop(self) -> None:
        """Background loop that posts status updates periodically."""
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            status = self.compute_status()
            if status:
                await channel.send(status)
        self.last_heartbeat = datetime.now(UTC)

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message) -> None:
        if message.author.bot:
            return

        content_lower = message.content.lower()
        if "lazarus" not in content_lower:
            return

        # Craft a response using the cold persona and then learn from the
        # incoming message.  Learning happens **after** generating the reply so
        # any memory reference in the response reflects the previous message
        # rather than echoing the current input.
        reply = self.generate_response(message.content)
        self.learn_from(message.content)
        await message.channel.send(reply)

    @nextcord.slash_command(name="lazarus", description="Lazarus AI controls", guild_ids=[GUILD_ID])
    async def lazarus_root(self, interaction: nextcord.Interaction):
        pass

    @lazarus_root.subcommand(name="status", description="Show Lazarus status")
    async def lazarus_status(self, interaction: nextcord.Interaction):
        if interaction.channel.id != self.channel_id:
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return
        status = self.compute_status() or "All systems nominal."
        await interaction.response.send_message(status)
