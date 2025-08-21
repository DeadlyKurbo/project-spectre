import os, datetime, traceback
import nextcord
from config import get_log_channel, DEFAULT_LOG_CHANNEL_ID

LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "actions.log")

def _ts() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()

async def log_action(bot: nextcord.Client, message: str):
    line = f"{_ts()} {message}"
    # Try Discord
    try:
        log_channel_id = get_log_channel() or DEFAULT_LOG_CHANNEL_ID
        channel = bot.get_channel(log_channel_id) or await bot.fetch_channel(log_channel_id)
        if channel:
            await channel.send(message)
    except Exception:
        pass
    # Fallback: local file
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
