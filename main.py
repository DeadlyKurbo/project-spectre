import os, nextcord, datetime
from nextcord.ext import commands, tasks
from nextcord import Embed

from config import (
    TOKEN, ROOT_PREFIX, MENU_CHANNEL_ID, UPLOAD_CHANNEL_ID,
    INTRO_TITLE, INTRO_DESC, GUILD_ID, BACKUP_INTERVAL_MIN
)

# ---- tolerant imports (flat of pakket) ----
try:
    from explorer_views import RootView
except ModuleNotFoundError:
    from views.explorer_views import RootView  # fallback

try:
    from archivist_views import UploadFileView, _backup_now
except ModuleNotFoundError:
    from views.archivist_views import UploadFileView, _backup_now  # fallback

from storage_spaces import ensure_dir
from logging_utils import log_action

try:
    import archivist_cmds, menu_cmds, mission_cmds
except ModuleNotFoundError:
    from commands import archivist_cmds, menu_cmds, mission_cmds  # fallback

intents = nextcord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(intents=intents)

async def handle_upload(message: nextcord.Message):
    try:
        from file_ops import create_dossier_file, list_categories
    except ModuleNotFoundError:
        from utils.file_ops import create_dossier_file, list_categories
    category = (message.content or "").strip().lower().replace(" ", "_")
    if not category:
        return await message.channel.send("❌ Add the category name in the message text.")
    if category not in list_categories():
        return await message.channel.send(f"❌ Unknown category `{category}`.")

    processed = False
    for attachment in message.attachments:
        if not (attachment.filename.lower().endswith(".json") or attachment.filename.lower().endswith(".txt")):
            continue
        data = (await attachment.read()).decode("utf-8", errors="replace")
        is_json = attachment.filename.lower().endswith(".json")
        base_no_ext = os.path.splitext(attachment.filename)[0]
        item_rel_input = base_no_ext if is_json else attachment.filename
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
    if UPLOAD_CHANNEL_ID and message.channel.id == UPLOAD_CHANNEL_ID:
        await handle_upload(message)

@bot.event
async def on_ready():
    print(f"✅ SPECTRE online as {bot.user}")
    ensure_dir(ROOT_PREFIX)
    for cat in ("missions", "personnel", "intelligence"):  # 'acl' en '_backups' tonen we niet
        ensure_dir(f"{ROOT_PREFIX}/{cat}")

    # persistent view
    bot.add_view(RootView(bot, INTRO_TITLE, INTRO_DESC))

    # hoofdmenu plaatsen
    if MENU_CHANNEL_ID:
        ch = bot.get_channel(MENU_CHANNEL_ID)
        if ch:
            await ch.send(
                embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
                view=RootView(bot, INTRO_TITLE, INTRO_DESC)
            )

    # force slash sync (anders zie je geen commands)
    try:
        if GUILD_ID:
            await bot.sync_application_commands(guild_id=GUILD_ID)
        else:
            await bot.sync_application_commands()
    except Exception as e:
        await log_action(bot, f"Command sync error: {e}")

# ---- Periodic backup loop ----
@tasks.loop(minutes=BACKUP_INTERVAL_MIN)
async def backup_loop():
    try:
        await _backup_now(bot)
    except Exception as e:
        try:
            await log_action(bot, f"Backup loop error: {e}")
        except Exception:
            pass

@bot.event
async def on_connect():
    try:
        if not backup_loop.is_running():
            backup_loop.start()
    except Exception:
        pass

# register slash commands
archivist_cmds.register(bot)
menu_cmds.register(bot)
mission_cmds.register(bot)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set.")
    bot.run(TOKEN)
