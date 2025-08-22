import os
import random
import asyncio
from datetime import datetime, UTC, timedelta
import nextcord
from nextcord import Embed
from nextcord.ext import commands, tasks

from constants import (
    TOKEN,
    GUILD_ID,
    MENU_CHANNEL_ID,
    ROOT_PREFIX,
    UPLOAD_CHANNEL_ID,
    DEFAULT_LOG_CHANNEL_ID,
    INTRO_TITLE,
    INTRO_DESC,
    REG_ARCHIVIST_TITLE,
    REG_ARCHIVIST_DESC,
    LEAD_ARCHIVIST_TITLE,
    LEAD_ARCHIVIST_DESC,
)
from config import get_log_channel, set_log_channel, get_build_version
from storage_spaces import (
    ensure_dir,
    save_text,
    read_text,
    list_dir,
    save_json,
    read_json,
    delete_file,
)
from dossier import ts, list_categories
from acl import get_required_roles, grant_file_clearance, revoke_file_clearance
from views import CategorySelect, RootView
from archivist import (
    handle_upload,
    ArchivistConsoleView,
    ArchivistLimitedConsoleView,
    _is_archivist,
    _is_lead_archivist,
)

intents = nextcord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(intents=intents)
LOG_CHANNEL_ID = get_log_channel() or DEFAULT_LOG_CHANNEL_ID
LOG_FILE = os.path.join(os.path.dirname(__file__), "actions.log")
HEARTBEAT_INTERVAL_HOURS = int(os.getenv("HEARTBEAT_INTERVAL_HOURS", "2"))
HICCUP_CHANCE = float(os.getenv("HICCUP_CHANCE", "0"))
BACKUP_INTERVAL_HOURS = int(os.getenv("BACKUP_INTERVAL_HOURS", "2"))

SESSION_ID = "".join(random.choices("ABCDEF0123456789", k=6))
FLAVOUR_LINES = [
    "Running integrity scan… All nodes stable.",
    "Detected abnormal packet latency. Monitoring…",
    "All sectors quiet. Awaiting new directives.",
]
NEXT_BACKUP_TS = datetime.now(UTC) + timedelta(hours=BACKUP_INTERVAL_HOURS)


def _count_all_files(prefix: str) -> int:
    """Recursively count all files under the given prefix."""
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


def _backup_all() -> tuple[datetime, str]:
    """Create a full archive backup under ``backups/`` and return timestamp and path."""
    data: dict[str, str] = {}

    def _recurse(pref: str) -> None:
        dirs, files = list_dir(pref, limit=10000)
        for fname, _ in files:
            path = f"{pref}/{fname}" if pref else fname
            try:
                data[path] = read_text(path)
            except Exception:
                continue
        for d in dirs:
            _recurse(f"{pref}/{d.strip('/')}")

    _recurse(ROOT_PREFIX)
    ts = datetime.now(UTC)
    ensure_dir("backups")
    fname = f"backups/{ts.strftime('%Y%m%dT%H%M%SZ')}.json"
    save_json(fname, data)
    return ts, fname


def _restore_backup(path: str) -> None:
    """Load a full archive backup from ``path``.

    Existing files under ``ROOT_PREFIX`` are removed if they are not present in
    the backup to ensure the restored state matches the snapshot exactly.
    """

    data = read_json(path)

    # Gather all current files
    existing: list[str] = []

    def _collect(pref: str) -> None:
        dirs, files = list_dir(pref, limit=10000)
        for fname, _ in files:
            existing.append(f"{pref}/{fname}" if pref else fname)
        for d in dirs:
            _collect(f"{pref}/{d.strip('/')}")

    _collect(ROOT_PREFIX)

    # Delete files not present in backup
    for fname in set(existing) - set(data.keys()):
        try:
            delete_file(fname)
        except Exception:
            pass

    # Restore files from backup
    for fname, content in data.items():
        save_text(fname, content)


async def log_action(message: str):
    line = f"{ts()} {message}"
    try:
        if LOG_CHANNEL_ID:
            channel = bot.get_channel(LOG_CHANNEL_ID) or await bot.fetch_channel(LOG_CHANNEL_ID)
            if channel:
                await channel.send(message)
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    try:
        existing = ""
        try:
            existing = read_text("logs/actions.log")
        except Exception:
            existing = ""
        save_text("logs/actions.log", existing + line + "\n")
    except Exception:
        pass


def get_user_logs(name: str, limit: int = 10):
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r", encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if name in line]
    return lines[-limit:]


def get_file_logs(fname: str):
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if fname in line]


async def maybe_simulate_hiccup(interaction: nextcord.Interaction) -> bool:
    if random.random() < HICCUP_CHANCE:
        await interaction.response.send_message(
            "❗ Node ECHO-04 failed to respond, rerouting… please hold.",
            ephemeral=True,
        )
        await asyncio.sleep(random.randint(3, 5))
        await interaction.edit_original_message(
            content="❗ Node ECHO-04 failed to respond, rerouting… please hold. Connection restored."
        )
        await log_action(
            "❗ Node ECHO-04 failed to respond, rerouting… please hold. Connection restored."
        )
        return True
    return False


def _generate_status_message() -> str:
    """Build a status string with live archive information."""
    file_count = _count_all_files(ROOT_PREFIX)
    last_mod = "N/A"
    logs: list[str] = []
    try:
        logs = read_text("logs/actions.log").strip().splitlines()
        if logs:
            ts_str = logs[-1].split(" ", 1)[0]
            last_dt = datetime.fromisoformat(ts_str)
            last_mod = f"<t:{int(last_dt.timestamp())}:T>"
    except Exception:
        if os.path.exists(LOG_FILE):
            last_dt = datetime.fromtimestamp(os.path.getmtime(LOG_FILE), UTC)
            last_mod = f"<t:{int(last_dt.timestamp())}:T>"

    now_dt = datetime.now(UTC)
    now = f"<t:{int(now_dt.timestamp())}:T>"
    past_hour = now_dt - timedelta(hours=1)
    reads = edits = requests = approved = denied = 0
    counts: dict[str, int] = {}
    for line in reversed(logs):
        try:
            ts_str, msg = line.split(" ", 1)
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            continue
        if ts < past_hour:
            break
        parts = msg.split()
        if len(parts) > 1:
            user = parts[1]
            counts[user] = counts.get(user, 0) + 1
        if "accessed `" in msg:
            reads += 1
        if any(k in msg for k in ["uploaded", "deleted", "edited", "updated", "removed"]):
            edits += 1
        if "requested clearance for" in msg:
            requests += 1
        if "granted" in msg and "access to" in msg:
            approved += 1
        if "denied" in msg and "access to" in msg:
            denied += 1

    top_user, top_actions = ("N/A", 0)
    if counts:
        top_user, top_actions = max(counts.items(), key=lambda x: x[1])
    pending = max(requests - (approved + denied), 0)
    next_backup = (
        f"<t:{int(NEXT_BACKUP_TS.timestamp())}:R>" if NEXT_BACKUP_TS else "N/A"
    )
    build = get_build_version()
    top_display = f"@{top_user.split('#')[0]}" if top_user != "N/A" else "N/A"

    lines = [
        random.choice(FLAVOUR_LINES),
        "",
        "**System Node Health**",
        "🟢 Node Alpha: ONLINE • 🔴 Node Echo: OFFLINE",
        "",
        "**Archive Overview**",
        f"Files stored: {file_count}",
        f"Last action: {last_mod}",
        f"Current time: {now}",
        "",
        "**Access Breakdown (1h)**",
        f"File accesses: {reads + edits} (📄 reads: {reads} • ✏️ edits: {edits})",
        (
            f"Requests: {requests} (approved: {approved} • denied: {denied} • pending: {pending})"
        ),
        "",
        "**Top Archivist of the Hour**",
        f"🏆 {top_display} ({top_actions} actions)",
        "",
        f"📦 Next backup scheduled: {next_backup}",
        "",
        f"SID: {SESSION_ID} • Build: {build}",
    ]
    return "\n".join(lines)


async def _heartbeat_action():
    await log_action(_generate_status_message())


@tasks.loop(hours=HEARTBEAT_INTERVAL_HOURS)
async def heartbeat_loop():
    await _heartbeat_action()


async def _backup_action():
    global NEXT_BACKUP_TS
    ts, fname = _backup_all()
    await log_action(f"📦 Backup saved to `{fname}`.")
    # Remove old backups beyond the 4 most recent
    try:
        _dirs, files = list_dir("backups", limit=1000)
        names = sorted(f for f, _ in files)
        while len(names) > 4:
            old = names.pop(0)
            try:
                delete_file(f"backups/{old}")
            except Exception:
                pass
    except Exception:
        pass
    NEXT_BACKUP_TS = datetime.now(UTC) + timedelta(hours=BACKUP_INTERVAL_HOURS)


@tasks.loop(hours=BACKUP_INTERVAL_HOURS)
async def backup_loop():
    await _backup_action()


@bot.event
async def on_ready():
    print(f"✅ SPECTRE online as {bot.user}")
    ensure_dir(ROOT_PREFIX)
    for cat in ("missions", "personnel", "intelligence", "acl"):
        ensure_dir(f"{ROOT_PREFIX}/{cat}")
    bot.add_view(RootView())
    main_ch = bot.get_channel(MENU_CHANNEL_ID)
    if main_ch:
        await main_ch.send(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=RootView(),
        )
    if not heartbeat_loop.is_running():
        heartbeat_loop.start()
    if not backup_loop.is_running():
        backup_loop.start()


@bot.event
async def on_message(message: nextcord.Message):
    if message.author.bot:
        return
    if message.channel.id != UPLOAD_CHANNEL_ID:
        return
    await handle_upload(message)


@bot.slash_command(name="archivist", description="Open the Archivist Console", guild_ids=[GUILD_ID])
async def archivist_cmd(interaction: nextcord.Interaction):
    if not _is_archivist(interaction.user):
        return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
    sender = interaction.response.send_message
    if await maybe_simulate_hiccup(interaction):
        sender = interaction.followup.send
    is_lead = _is_lead_archivist(interaction.user)
    view = (
        ArchivistConsoleView(interaction.user)
        if is_lead
        else ArchivistLimitedConsoleView(interaction.user)
    )
    if is_lead:
        embed = Embed(
            title=LEAD_ARCHIVIST_TITLE,
            description=LEAD_ARCHIVIST_DESC,
            color=0x3C2E7D,
        )
    else:
        embed = Embed(
            title=REG_ARCHIVIST_TITLE,
            description=REG_ARCHIVIST_DESC,
            color=0x0FA3B1,
        )
    await sender(embed=embed, view=view, ephemeral=True)


@bot.slash_command(name="summonmenu", description="Resend the explorer menu", guild_ids=[GUILD_ID])
async def summonmenu_cmd(interaction: nextcord.Interaction):
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
    ):
        return await interaction.response.send_message("⛔ Admin/Owner only.", ephemeral=True)
    sender = interaction.response.send_message
    if await maybe_simulate_hiccup(interaction):
        sender = interaction.followup.send
    await sender(
        embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
        view=RootView(),
    )
    await log_action(f"📣 {interaction.user} summoned the file explorer menu.")


@bot.slash_command(name="setlogchannel", description="Set the logging channel", guild_ids=[GUILD_ID])
async def setlogchannel_cmd(interaction: nextcord.Interaction, channel: nextcord.TextChannel):
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
    ):
        return await interaction.response.send_message("⛔ Admin/Owner only.", ephemeral=True)
    global LOG_CHANNEL_ID
    set_log_channel(channel.id)
    LOG_CHANNEL_ID = channel.id
    sender = interaction.response.send_message
    if await maybe_simulate_hiccup(interaction):
        sender = interaction.followup.send
    await sender(
        f"✅ Log channel set to {channel.mention}.", ephemeral=True
    )
    await log_action(f"🛠 {interaction.user} set the log channel to {channel.mention}.")


@bot.slash_command(name="logs", description="Query the archive logs", guild_ids=[GUILD_ID])
async def logs_root(interaction: nextcord.Interaction):
    pass


@logs_root.subcommand(name="user", description="Show last 10 archive interactions for a user")
async def logs_user(interaction: nextcord.Interaction, member: nextcord.Member):
    sender = interaction.response.send_message
    if await maybe_simulate_hiccup(interaction):
        sender = interaction.followup.send
    lines = get_user_logs(str(member))
    content = "\n".join(lines) if lines else "No log entries found."
    await sender(content, ephemeral=True)


@logs_root.subcommand(name="file", description="Show all access/edit events for a file")
async def logs_file(interaction: nextcord.Interaction, filename: str):
    sender = interaction.response.send_message
    if await maybe_simulate_hiccup(interaction):
        sender = interaction.followup.send
    lines = get_file_logs(filename)
    content = "\n".join(lines) if lines else "No log entries found."
    await sender(content, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set.")
    bot.run(TOKEN)
