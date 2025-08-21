import os, nextcord
from nextcord.ext import commands, tasks
from nextcord import Embed

from config import TOKEN, ROOT_PREFIX, MENU_CHANNEL_ID, UPLOAD_CHANNEL_ID, INTRO_TITLE, INTRO_DESC, GUILD_ID
from storage_spaces import ensure_dir, save_text, read_text, read_json, list_dir
from utils.logging_utils import log_action
from views.explorer_views import RootView
from views.archivist_views import UploadFileView
from commands import archivist_cmds, menu_cmds, mission_cmds

intents = nextcord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(intents=intents)

async def handle_upload(message: nextcord.Message):
    from utils.file_ops import create_dossier_file
    category = (message.content or "").strip().lower().replace(" ", "_")
    if not category:
        return await message.channel.send("❌ Add the category name in the message text.")
    from utils.file_ops import list_categories
    if category not in list_categories():
        return await message.channel.send(f"❌ Unknown category `{category}`.")

    processed = False
    for attachment in message.attachments:
        if not (attachment.filename.lower().endswith(".json") or attachment.filename.lower().endswith(".txt")):
            continue
        data = (await attachment.read()).decode("utf-8", errors="replace")
        is_json = attachment.filename.lower().endswith(".json")
        item_rel_input = os.path.splitext(attachment.filename)[0] if is_json else attachment.filename
        try:
            key = create_dossier_file(category, item_rel_input, data, prefer_txt_default=not is_json)
        except FileExistsError:
            await message.channel.send(f"⚠️ `{item_rel_input}` already exists.")
        else:
            await message.channel.send(f"✅ Added `{item_rel_input}` to `{category}`.")
            await log_action(bot, f"⬆️ {message.author} uploaded `{category}/{item_rel_input}` → `{key}`.")
            processed = True

    if not processed:
        await message.channel.send("❌ No .json/.txt files found in the upload.")

@bot.event
async def on_message(message: nextcord.Message):
    if message.author.bot:
        return
    if message.channel.id != UPLOAD_CHANNEL_ID:
        return
    await handle_upload(message)

@bot.event
async def on_ready():
    print(f"✅ SPECTRE online as {bot.user}")
    ensure_dir(ROOT_PREFIX)
    for cat in ("missions", "personnel", "intelligence", "acl"):
        ensure_dir(f"{ROOT_PREFIX}/{cat}")

    bot.add_view(RootView(bot, INTRO_TITLE, INTRO_DESC))  # persistent

    main_ch = bot.get_channel(MENU_CHANNEL_ID)
    if main_ch:
        await main_ch.send(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=RootView(bot, INTRO_TITLE, INTRO_DESC)
        )

    up_ch = bot.get_channel(UPLOAD_CHANNEL_ID)
    if up_ch:
        await up_ch.send(
            embed=Embed(
                title="Archive Uplink",
                description="Use `/archivist` for the full console or post attachments here with the category name as the message.",
                color=0x00FFCC
            )
        )

# register slash commands
archivist_cmds.register(bot)
menu_cmds.register(bot)
mission_cmds.register(bot)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set.")
    bot.run(TOKEN)


from config import BACKUP_DIR, BACKUP_INTERVAL_MIN, MISSION_CHANNEL_ID
from views.archivist_views import _backup_now
import datetime, asyncio

@tasks.loop(minutes=BACKUP_INTERVAL_MIN)
async def backup_loop():
    try:
        await _backup_now(bot)
    except Exception as e:
        try:
            await log_action(bot, f"Backup loop error: {e}")
        except Exception:
            pass

@tasks.loop(minutes=1)
async def mission_checker():
    # fire reminders for due missions
    from commands.mission_cmds import _load, _save
    now = datetime.datetime.now(datetime.timezone.utc)
    db = _load()
    keep = []
    for m in db.get("missions", []):
        try:
            when = datetime.datetime.fromisoformat(m["when"])
        except Exception:
            keep.append(m); continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        if when <= now:
            try:
                ch = bot.get_channel(int(m["channel_id"])) or await bot.fetch_channel(int(m["channel_id"]))
                if ch:
                    await ch.send(f"📣 **Mission Reminder:** {m['title']} (scheduled {m['when']})")
            except Exception:
                pass
        else:
            keep.append(m)
    if keep != db.get("missions"):
        db["missions"] = keep
        _save(db)

@bot.event
async def on_connect():
    try:
        if not backup_loop.is_running():
            backup_loop.start()
        if not mission_checker.is_running():
            mission_checker.start()
    except Exception:
        pass
