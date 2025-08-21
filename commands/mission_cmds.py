
import datetime, json, nextcord
from nextcord import Embed
from config import GUILD_ID, MISSION_CHANNEL_ID
from storage_spaces import ensure_dir, read_json, save_json

MISSIONS_KEY = "dossiers/_missions/missions.json"

def _load():
    try: return read_json(MISSIONS_KEY)
    except Exception: return {"missions":[]}

def _save(db): save_json(MISSIONS_KEY, db)

def register(bot: nextcord.Client):
    @bot.slash_command(name="mission_add", description="Add a mission reminder", guild_ids=[GUILD_ID])
    async def mission_add(inter: nextcord.Interaction, title: str, when_iso: str, channel: nextcord.TextChannel = None):
        # when_iso: 2025-08-22T23:30:00Z
        try:
            when = datetime.datetime.fromisoformat(when_iso.replace("Z","+00:00"))
        except Exception:
            return await inter.response.send_message("Use ISO format like 2025-08-22T23:30:00Z", ephemeral=True)
        db = _load()
        db["missions"].append({"title": title, "when": when.isoformat(), "channel_id": channel.id if channel else (MISSION_CHANNEL_ID or inter.channel.id)})
        _save(db)
        await inter.response.send_message(f"✅ Scheduled **{title}** at {when_iso}", ephemeral=True)

    @bot.slash_command(name="mission_list", description="List upcoming missions", guild_ids=[GUILD_ID])
    async def mission_list(inter: nextcord.Interaction):
        db = _load()
        if not db["missions"]:
            return await inter.response.send_message("No missions.", ephemeral=True)
        lines = [f"- {m['title']} — {m['when']} → <#{m['channel_id']}> " for m in db["missions"]]
        await inter.response.send_message("\\n".join(lines[:20]), ephemeral=True)
