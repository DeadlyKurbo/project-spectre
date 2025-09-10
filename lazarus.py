"""Lazarus AI core.

This module originally only exposed a minimal health monitor.  In order to
make the agent more responsive and give it basic learning capabilities we add
a very small conversational layer.  The goal is not to build a full blown
language model but to provide a deterministic, "cold" interaction style that
logs messages and can surface information from the archive storage. The AI
only replies inside its designated channel.
"""

from datetime import datetime, UTC, timedelta
from typing import List, Dict, Any
import difflib
import re
from pathlib import Path

import nextcord
from nextcord.ext import commands, tasks

from constants import (
    GUILD_ID,
    LEVEL1_ROLE_ID,
    LEVEL2_ROLE_ID,
    LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID,
    LEVEL5_ROLE_ID,
    CLASSIFIED_ROLE_ID,
)
from roster import ROSTER_ROLES
from storage_spaces import read_text, read_json, save_json, save_text
import llm_client

# File within the configured storage where Lazarus persists a minimal memory
LAZARUS_MEMORY_PATH = "lazarus/memory.json"

class LazarusAI(commands.Cog):
    """Minimal hidden AI core monitoring the guild.

    The cog maintains a silent background loop (``shadow_loop``) which checks
    for basic health indicators such as a heartbeat and the age of the most
    recent backup. Status messages are posted to the designated channel and a
    ``/lazarus status`` command exposes the current health summary on demand.
    The AI only engages in conversation inside that channel, ignoring all other
    channels entirely.
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

    # Mapping of clearance roles to human readable levels ordered from highest
    # to lowest.  Used to determine an operator's clearance when interacting
    # with the AI.
    CLEARANCE_LEVELS = [
        (CLASSIFIED_ROLE_ID, "Classified"),
        (LEVEL5_ROLE_ID, "L5"),
        (LEVEL4_ROLE_ID, "L4"),
        (LEVEL3_ROLE_ID, "L3"),
        (LEVEL2_ROLE_ID, "L2"),
        (LEVEL1_ROLE_ID, "L1"),
    ]

    def _user_rank(self, member: nextcord.abc.User | None) -> str:
        """Return the human friendly rank name for ``member``."""
        roles = getattr(member, "roles", [])
        for role_id, _emoji, name in ROSTER_ROLES:
            if any(r.id == role_id for r in roles):
                return name
        return "Unknown"

    def _user_clearance(self, member: nextcord.abc.User | None) -> str:
        """Return the highest clearance level for ``member``."""
        roles = getattr(member, "roles", [])
        for role_id, label in self.CLEARANCE_LEVELS:
            if any(r.id == role_id for r in roles):
                return label
        return "None"

    def learn_from(self, text: str, member: nextcord.abc.User | None = None) -> None:
        """Record a new observation in memory."""
        entry = {"ts": datetime.now(UTC).isoformat(), "text": text}
        if member is not None:
            entry["rank"] = self._user_rank(member)
            entry["clearance"] = self._user_clearance(member)
            uid = getattr(member, "id", None)
            if uid is not None:
                entry["user_id"] = uid
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

    # ------------------------------------------------------------------
    # File search and edit helpers
    def _search_file(self, query: str) -> str | None:
        """Search the repository for a file matching ``query``.

        The search is case-insensitive and falls back to a fuzzy match when no
        direct substring matches are found. Returns the relative path of the
        best candidate or ``None`` if nothing matches.
        """
        query_low = query.lower().strip()
        repo_root = Path(".")
        candidates: list[str] = []
        for p in repo_root.rglob("*"):
            if p.is_file():
                rel = str(p)
                candidates.append(rel)
                if rel.lower() == query_low or p.name.lower() == query_low:
                    return rel
        if not candidates:
            return None
        # Substring match
        for c in candidates:
            if query_low in c.lower():
                return c
        # Fuzzy match
        lowered = [c.lower() for c in candidates]
        match = difflib.get_close_matches(query_low, lowered, n=1)
        if match:
            idx = lowered.index(match[0])
            return candidates[idx]
        return None

    def _parse_edit_request(self, text: str) -> tuple[str, str] | None:
        """Return (path, content) if the text requests a file edit."""
        m = re.search(r"edit\s+([^\s]+)\s+to\s+(.+)", text, re.IGNORECASE | re.DOTALL)
        if m:
            path = m.group(1).strip()
            content = m.group(2).strip()
            return path, content
        return None

    def edit_file(self, path: str, new_content: str) -> str:
        """Overwrite ``path`` with ``new_content`` using fuzzy search."""
        target = path
        try:
            save_text(target, new_content)
            return "File updated."
        except Exception:
            found = self._search_file(path)
            if not found:
                return "File not found."
            try:
                save_text(found, new_content)
                return "File updated."
            except Exception:
                return "Unable to edit file."

    def generate_response(self, prompt: str, member: nextcord.abc.User | None = None) -> str:
        """Generate a response for ``prompt`` using the LLM client.

        When ``member`` is provided the prompt is augmented with the operator's
        rank and clearance level so the model can tailor its behaviour. Falls
        back to a simple acknowledgement when the LLM is unavailable.
        """
        if member is not None:
            rank = self._user_rank(member)
            clearance = self._user_clearance(member)
            prompt = (
                f"Operator rank: {rank}\n"
                f"Operator clearance: {clearance}\n"
                f"Message: {prompt}"
            )
        try:
            return llm_client.run_assistant(prompt)
        except Exception:
            return "Acknowledged."

    def _parse_summary_request(self, text: str) -> str | None:
        """Return the requested file path when asking for a summary."""
        marker = "sum up of"
        lower = text.lower()
        if marker in lower:
            start = lower.index(marker) + len(marker)
            path = text[start:].strip().rstrip(" .?!")
            return path or None
        return None

    def summarize_file(self, path: str) -> str:
        """Read a file and return a short summary."""
        target = path
        try:
            content = read_text(target)
        except FileNotFoundError:
            found = self._search_file(path)
            if not found:
                return "File not found."
            try:
                content = read_text(found)
            except Exception:
                return "Unable to read file."
        except Exception:
            return "Unable to read file."
        prompt = f"Summarize the following text:\n\n{content}"
        try:
            summary = llm_client.run_assistant(prompt)
        except Exception:
            return "Summary unavailable."
        return f"Understood, {summary}"

    @tasks.loop(minutes=1)
    async def shadow_loop(self) -> None:
        """Background loop that posts status updates periodically."""
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            status = self.compute_status()
            if status:
                try:
                    await channel.send(status)
                except Exception:
                    pass
        self.last_heartbeat = datetime.now(UTC)

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message) -> None:
        if message.author.bot:
            return

        if message.channel.id != self.channel_id:
            return

        # Check if the message requests a file edit or summary
        edit_req = self._parse_edit_request(message.content)
        if edit_req:
            path, new_content = edit_req
            reply = self.edit_file(path, new_content)
        else:
            req = self._parse_summary_request(message.content)
            if req:
                reply = self.summarize_file(req)
            else:
                # Craft a response using the cold persona and then learn from the
                # incoming message.  Learning happens **after** generating the reply so
                # any memory reference in the response reflects the previous message
                # rather than echoing the current input.
                reply = self.generate_response(message.content, message.author)
        self.learn_from(message.content, message.author)
        try:
            await message.channel.send(reply)
        except Exception:
            pass

    @nextcord.slash_command(name="lazarus", description="Lazarus AI controls", guild_ids=[GUILD_ID])
    async def lazarus_root(self, interaction: nextcord.Interaction):
        pass

