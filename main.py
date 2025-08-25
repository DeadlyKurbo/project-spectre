import os
import random
import asyncio
import re
from datetime import datetime, UTC, timedelta
import nextcord
from nextcord import Embed
from nextcord.ext import commands, tasks

from constants import (
    TOKEN,
    GUILD_ID,
    MENU_CHANNEL_ID,
    ROSTER_CHANNEL_ID,
    ROOT_PREFIX,
    UPLOAD_CHANNEL_ID,
    DEFAULT_LOG_CHANNEL_ID,
    LAZARUS_CHANNEL_ID,
    INTRO_TITLE,
    INTRO_DESC,
    REG_ARCHIVIST_TITLE,
    REG_ARCHIVIST_DESC,
    LEAD_ARCHIVIST_TITLE,
    LEAD_ARCHIVIST_DESC,
    ARCHIVIST_ROLE_ID,
    TRAINEE_ARCHIVIST_TITLE,
    TRAINEE_ARCHIVIST_DESC,
    TRAINEE_ROLE_ID,
    CLASSIFIED_ROLE_ID,
    EPSILON_LAUNCH_CODE,
    OMEGA_KEY_FRAGMENT_1,
    OMEGA_KEY_FRAGMENT_2,
    OMEGA_BACKUP_PATH,
)
from omega_directive import OmegaDirectiveTest
from config import (
    get_log_channel,
    get_build_version,
    get_status_message_id,
    set_status_message_id,
)
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
    ArchivistTraineeConsoleView,
    _is_archivist,
    _is_lead_archivist,
)
from roster import send_roster, ROSTER_ROLES
from lazarus import LazarusAI

GREEK_LETTERS = [
    "Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta",
    "Iota", "Kappa", "Lambda", "Mu", "Nu", "Xi", "Omicron", "Pi",
    "Rho", "Sigma", "Tau", "Upsilon", "Phi", "Chi", "Psi", "Omega",
]

intents = nextcord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(intents=intents)
LOG_CHANNEL_ID = get_log_channel() or DEFAULT_LOG_CHANNEL_ID
LOG_FILE = os.path.join(os.path.dirname(__file__), "actions.log")
STATUS_REFRESH_MINUTES = int(os.getenv("STATUS_REFRESH_MINUTES", "1"))
STATUS_MESSAGE_ID = get_status_message_id()
HICCUP_CHANCE = float(os.getenv("HICCUP_CHANCE", "0"))
BACKUP_INTERVAL_HOURS = float(os.getenv("BACKUP_INTERVAL_HOURS", "0.5"))
LAZARUS_STATUS_INTERVAL = int(os.getenv("LAZARUS_STATUS_INTERVAL", "5"))

SESSION_ID = "".join(random.choices("ABCDEF0123456789", k=6))
FLAVOUR_LINES = [
    "Running integrity scan… All nodes stable.",
    "Detected abnormal packet latency. Monitoring…",
    "All sectors quiet. Awaiting new directives.",
    "Cycling node relays… energy readings nominal.",
    "Calibrating sensors… please stand by.",
    "Running diagnostics… ███░░░░░ 37%",
    "Spectral scan complete. No anomalies detected.",
    "Reactor output steady. Shields at 100%.",
    "Quantum uplink stable. Listening for transmissions.",
    "Nanite swarm performing routine maintenance.",
]
START_TIME = datetime.now(UTC)
NODE_CLUSTER = os.getenv("NODE_CLUSTER", "BOREAL-07")
LAST_BACKUP_TS: datetime | None = None

NODE_STATES = [
    "🟢 ONLINE (Nominal)",
    "🟡 DEGRADED (High latency)",
    "🔴 OFFLINE (Connection lost)",
    "🟣 MAINTENANCE (Manual override)",
]

NEXT_BACKUP_TS = datetime.now(UTC) + timedelta(hours=BACKUP_INTERVAL_HOURS)
lazarus_ai = LazarusAI(bot, LAZARUS_CHANNEL_ID, BACKUP_INTERVAL_HOURS, LAZARUS_STATUS_INTERVAL)
bot.add_cog(lazarus_ai)

RECENT_ACTION_KEYWORDS = [
    "attempted to access",
    "deleted",
    "accessed `",
    "uploaded",
    "edited",
    "annotated",
    "granted",
    "denied",
]


def _progress_bar(pct: float, length: int = 10) -> str:
    """Return a simple text progress bar for ``pct`` (0..1)."""
    pct = max(0.0, min(1.0, pct))
    filled = int(pct * length)
    return "█" * filled + "░" * (length - filled)


def _format_recent_action(line: str) -> str:
    """Transform a log line into a short summary with relative timestamps."""
    try:
        ts_str, msg = line.split(" ", 1)
        ts_dt = datetime.fromisoformat(ts_str)
        ts_disp = f"<t:{int(ts_dt.timestamp())}:R>"
    except Exception:
        return f"🗂️ {line}"
    if "accessed `" in msg:
        user = msg.split(" ")[1]
        file = msg.split("`")[1]
        return f"🗂️ {file} — read by {user} {ts_disp}"
    if "attempted to access" in msg:
        user = msg.split(" ")[1]
        file = msg.split("`")[1]
        return f"🗂️ {file} — access attempt by {user} {ts_disp}"
    if "edited `" in msg:
        user = msg.split(" ")[1]
        file = msg.split("`")[1]
        return f"🗂️ {file} — edit by {user} {ts_disp}"
    if "uploaded" in msg and "`" in msg:
        user = msg.split()[1]
        file = msg.split("`")[1]
        return f"🗂️ {file} — created by {user} {ts_disp}"
    if "deleted" in msg and "`" in msg:
        user = msg.split()[1]
        file = msg.split("`")[1]
        return f"🗂️ {file} — deleted by {user} {ts_disp}"
    if "annotated `" in msg:
        user = msg.split()[1]
        file = msg.split("`")[1]
        return f"🗂️ {file} — annotated by {user} {ts_disp}"
    if "Backup saved to `" in msg:
        file = msg.split("`")[1]
        return f"📦 Backup saved to {file} {ts_disp}"
    if "requested clearance for `" in msg:
        user = msg.split(" ")[1]
        file = msg.split("`")[1]
        return f"🗂️ {file} — clearance requested by {user} {ts_disp}"
    if "granted" in msg and "access to `" in msg:
        approver = msg.split()[1]
        file = msg.split("`")[1]
        return f"🗂️ {file} — approved by {approver} {ts_disp}"
    if "denied" in msg and "access to `" in msg:
        approver = msg.split()[1]
        file = msg.split("`")[1]
        return f"🗂️ {file} — denied by {approver} {ts_disp}"
    return f"🗂️ {msg} {ts_disp}"


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
    """Create a full archive backup under ``backups/`` and return timestamp and path.

    The backup file is named using a random Greek letter instead of a timestamp.
    """
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
    name = random.choice(GREEK_LETTERS)
    fname = f"backups/Backup protocol {name}.json"
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


def _purge_archive_and_backups() -> None:
    """Remove all files from the archive and backup storage."""

    def _purge(prefix: str) -> None:
        try:
            dirs, files = list_dir(prefix, limit=10000)
        except Exception:
            return
        for fname, _ in files:
            try:
                delete_file(f"{prefix}/{fname}" if prefix else fname)
            except Exception:
                continue
        for d in dirs:
            _purge(f"{prefix}/{d.strip('/')}")

    _purge(ROOT_PREFIX)
    _purge("backups")


async def log_action(message: str, *, broadcast: bool = True):
    line = f"{ts()} {message}"
    try:
        if broadcast and LOG_CHANNEL_ID:
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
    try:
        await update_status_message()
    except Exception:
        pass


async def update_status_message():
    """Create or refresh the persistent status message."""
    global STATUS_MESSAGE_ID
    try:
        channel = bot.get_channel(LOG_CHANNEL_ID) or await bot.fetch_channel(LOG_CHANNEL_ID)
    except Exception:
        return
    if not channel:
        return
    content = _generate_status_message()
    if STATUS_MESSAGE_ID:
        try:
            msg = await channel.fetch_message(STATUS_MESSAGE_ID)
            await msg.edit(content=content)
            return
        except Exception:
            STATUS_MESSAGE_ID = None
    try:
        msg = await channel.send(content)
        STATUS_MESSAGE_ID = msg.id
        set_status_message_id(STATUS_MESSAGE_ID)
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
    filtered_logs: list[str] = []
    try:
        logs = read_text("logs/actions.log").strip().splitlines()
        filtered_logs = [
            l
            for l in logs
            if any(k in l for k in RECENT_ACTION_KEYWORDS)
            and "trainee submission" not in l
        ]
        source = filtered_logs if filtered_logs else logs
        if source:
            ts_str = source[-1].split(" ", 1)[0]
            last_dt = datetime.fromisoformat(ts_str)
            last_mod = f"<t:{int(last_dt.timestamp())}:T>"
    except Exception:
        if os.path.exists(LOG_FILE):
            last_dt = datetime.fromtimestamp(os.path.getmtime(LOG_FILE), UTC)
            last_mod = f"<t:{int(last_dt.timestamp())}:T>"

    now_dt = datetime.now(UTC)
    now = f"<t:{int(now_dt.timestamp())}:T>"
    past_day = now_dt - timedelta(days=1)
    reads = edits = approved = denied = 0
    pending_requests: set[tuple[str, str]] = set()
    resolved_requests: set[tuple[str, str]] = set()
    user_pattern = r"(?:<@!?\d+>|@\w+)"
    request_re = re.compile(rf"({user_pattern}) requested clearance for `([^`]+)`")
    grant_re = re.compile(rf"granted ({user_pattern}) access to `([^`]+)`")
    deny_re = re.compile(rf"denied ({user_pattern}) access to `([^`]+)`")
    counts: dict[int | str, int] = {}
    for line in reversed(logs):
        try:
            ts_str, msg = line.split(" ", 1)
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            continue
        if ts < past_day:
            break
        parts = msg.split()
        if ts >= past_day and len(parts) > 1:
            user = parts[1]
            parsed_user: int | str | None = None
            if user.startswith("<@") and user.endswith(">"):
                try:
                    parsed_user = int(user.strip("<@!>"))
                except ValueError:
                    pass
            elif user.startswith("@"):
                parsed_user = user[1:]
            if parsed_user is not None:
                counts[parsed_user] = counts.get(parsed_user, 0) + 1
        if "accessed `" in msg:
            reads += 1
        if any(k in msg for k in ["uploaded", "deleted", "edited", "updated", "removed"]):
            edits += 1
        if m := grant_re.search(msg):
            approved += 1
            resolved_requests.add(m.group(1, 2))
        if m := deny_re.search(msg):
            denied += 1
            resolved_requests.add(m.group(1, 2))
        if m := request_re.search(msg):
            key = m.group(1, 2)
            if key not in resolved_requests:
                pending_requests.add(key)

    top_user, top_actions = ("N/A", 0)
    if counts:
        top_user, top_actions = max(counts.items(), key=lambda x: x[1])
    pending = len(pending_requests)
    next_backup_rel = (
        f"<t:{int(NEXT_BACKUP_TS.timestamp())}:R>" if NEXT_BACKUP_TS else "N/A"
    )
    if LAST_BACKUP_TS:
        last_backup_str = LAST_BACKUP_TS.strftime("%H:%MZ")
        total = (NEXT_BACKUP_TS - LAST_BACKUP_TS).total_seconds() if NEXT_BACKUP_TS else 0
        elapsed = (now_dt - LAST_BACKUP_TS).total_seconds()
        pct = 0 if total <= 0 else elapsed / total
    else:
        last_backup_str = "N/A"
        pct = 0
    backup_bar = _progress_bar(pct)
    build = get_build_version()
    if top_user != "N/A":
        guild = bot.get_guild(GUILD_ID)
        if isinstance(top_user, int):
            member = guild.get_member(top_user) if guild else None
            top_display = member.mention if member else f"<@{top_user}>"
        else:
            member = guild.get_member_named(top_user) if guild else None
            top_display = member.mention if member else f"@{top_user.split('#')[0]}"
    else:
        top_display = "N/A"
    access_total = reads + edits
    uptime = int((now_dt - START_TIME).total_seconds() // 3600)
    latency_ms = int(getattr(bot, "latency", 0) * 1000)
    connection = "Stable" if bot.is_ready() else "Reconnecting"
    avg_resp_ms = latency_ms + 20
    recent = [_format_recent_action(l) for l in filtered_logs[-3:]]

    lines = [
        random.choice(FLAVOUR_LINES),
        "",
        "⚙️ **System Node Health**",
        f"Node Alpha: {random.choice(NODE_STATES)}",
        f"Node Echo: {random.choice(NODE_STATES)}",
        f"📡 Bot ping: {latency_ms}ms",
        f"🔌 Connection: {connection}",
        f"⏱️ Avg response: {avg_resp_ms}ms",
        f"Backups: Next {next_backup_rel} • Last: {last_backup_str}",
        f"Next backup {backup_bar} ({int(pct*100)}%)",
        "",
        "📂 **Archive Overview**",
        f"Files stored: {file_count}",
        f"Last action: {last_mod}",
        f"Current time: {now}",
        f"Integrity: All {file_count} files verified • 0 mismatches",
        "",
        "📊 **Access Breakdown (24h)**",
        f"{access_total} accesses ({reads} read • {edits} edit)",
        f"✅ Approved: {approved}",
        f"❌ Denied: {denied}",
        f"🟠 Pending: {pending}",
        "",
        "🏆 **Top Archivist (24h)**",
        f"{top_display} ({top_actions} actions)",
        "",
        "🗂️ **Recent Actions**",
        *recent,
        "",
        f"Node Cluster: {NODE_CLUSTER} • Uptime: {uptime}h • Build: {build} • SID: {SESSION_ID}",
    ]
    return "\n".join(lines)


async def _heartbeat_action():
    await update_status_message()

@tasks.loop(minutes=STATUS_REFRESH_MINUTES)
async def heartbeat_loop():
    await _heartbeat_action()


async def _backup_action():
    global NEXT_BACKUP_TS, LAST_BACKUP_TS
    ts, fname = _backup_all()
    LAST_BACKUP_TS = ts
    try:
        lazarus_ai.note_backup(ts)
    except Exception:
        pass
    await log_action(f"📦 Backup saved to `{fname}`.", broadcast=False)
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
    roster_ch = bot.get_channel(ROSTER_CHANNEL_ID)
    if roster_ch:
        try:
            await send_roster(roster_ch, roster_ch.guild)
        except Exception:
            pass
    if not heartbeat_loop.is_running():
        heartbeat_loop.start()
    if not backup_loop.is_running():
        backup_loop.start()
    lazarus_ai.start()


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
    user_roles = {r.id for r in interaction.user.roles}
    is_trainee = TRAINEE_ROLE_ID in user_roles and not is_lead and ARCHIVIST_ROLE_ID not in user_roles
    view = (
        ArchivistConsoleView(interaction.user)
        if is_lead
        else ArchivistTraineeConsoleView(interaction.user)
        if is_trainee
        else ArchivistLimitedConsoleView(interaction.user)
    )
    if is_lead:
        embed = Embed(
            title=LEAD_ARCHIVIST_TITLE,
            description=LEAD_ARCHIVIST_DESC,
            color=0x3C2E7D,
        )
    elif is_trainee:
        embed = Embed(
            title=TRAINEE_ARCHIVIST_TITLE,
            description=TRAINEE_ARCHIVIST_DESC,
            color=0x00FFCC,
        )
    else:
        embed = Embed(
            title=REG_ARCHIVIST_TITLE,
            description=REG_ARCHIVIST_DESC,
            color=0x0FA3B1,
        )
    await sender(embed=embed, view=view, ephemeral=True)


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


async def apply_protocol_epsilon(guild: nextcord.Guild, classified_role: nextcord.Role) -> None:
    for channel in guild.channels:
        for role in guild.roles:
            if role.position < classified_role.position:
                try:
                    await channel.set_permissions(
                        role,
                        send_messages=False,
                        add_reactions=False,
                        connect=False,
                        speak=False,
                    )
                except Exception:
                    continue

    rank_role_ids = [rid for rid, _, _ in ROSTER_ROLES[2:]]
    for member in getattr(guild, "members", []):
        roles_to_remove = [r for r in getattr(member, "roles", []) if r.id in rank_role_ids]
        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove)
            except Exception:
                continue


async def execute_epsilon_actions(
    guild: nextcord.Guild, classified_role: nextcord.Role
) -> None:
    """Perform all final actions for Protocol Epsilon."""

    await apply_protocol_epsilon(guild, classified_role)
    _purge_archive_and_backups()
    await log_action("🧨 Protocol EPSILON purge executed.")


async def execute_omega_actions(guild: nextcord.Guild) -> None:
    """Restore system state from the hidden Omega backup."""

    try:
        _restore_backup(OMEGA_BACKUP_PATH)
        await log_action("🔄 Omega Directive restoration executed.")
    except Exception as e:
        await log_action(f"❗ Omega restore error: {e}")

@bot.slash_command(
    name="protocol-epsilon",
    description="🚨WARNING ONLY ACTIVATE UNDER GUIDANCE OF FILE EPSILON🚨",
    guild_ids=[GUILD_ID],
)
async def protocol_epsilon(interaction: nextcord.Interaction):
    classified_role = interaction.guild.get_role(CLASSIFIED_ROLE_ID)
    if not classified_role:
        return await interaction.response.send_message(
            "Classified Clearance role not found.", ephemeral=True
        )
    if interaction.user.top_role.position < classified_role.position:
        return await interaction.response.send_message(
            "⛔ Classified clearance required.", ephemeral=True
        )

    warning_one = (
        "[ACCESS NODE: EPSILON]\n"
        "> Command Detected: /protocol-epsilon\n"
        "> Warning: This action will trigger FINAL CONTINGENCY PROTOCOL.\n"
        "──────────────────────────────\n"
        "⚠️  WARNING EPSILON IS A NO-FAIL PROTOCOL\n"
        "Once initiated, all GU7 systems will:\n"
        "- Lock all archives fleet-wide\n"
        "- Terminate all active operations\n"
        "- Prepare HQ for data purge & shutdown\n\n"
        "Only Command Authority L5+ may proceed.\n"
        "──────────────────────────────"
    )

    warning_two = (
        "[FINAL WARNING: EPSILON ACTIVATION]\n"
        "This action cannot be undone.\n"
        "You are about to execute Glacier Unit 7’s final contingency plan.\n\n"
        "Protocol EPSILON = Complete operational collapse.\n\n"
        "Estimated Effects:\n"
        "• Archive lockdown: Immediate\n"
        "• Data purge: Phase One in 60 sec\n"
        "• System lockdown: Total\n"
        "──────────────────────────────\n"
        "Type secret launch code to proceed.\n"
        "──────────────────────────────"
    )

    final_screen = (
        "> EPSILON Activation Confirmed\n"
        "> Authorization Code: L5 // COMMAND NODE ALPHA\n"
        "> Initiating FINAL CONTINGENCY PROTOCOL...\n"
        "──────────────────────────────\n"
        "🚨 ALERT  PROTOCOL EPSILON IS NOW ACTIVE 🚨\n"
        "Glacier HQ will enter full lockdown in T-60 seconds."
    )

    class ConfirmModal(nextcord.ui.Modal):
        def __init__(self):
            super().__init__(title="EPSILON CONFIRMATION")
            self.input = nextcord.ui.TextInput(
                label="Type secret launch code"
            )
            self.add_item(self.input)

        async def callback(self, modal_interaction: nextcord.Interaction):
            if modal_interaction.user != interaction.user:
                return await modal_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            if self.input.value.strip() != EPSILON_LAUNCH_CODE:
                return await modal_interaction.response.send_message(
                    "Authorization failed. Protocol aborted."
                )
            await execute_epsilon_actions(interaction.guild, classified_role)
            await modal_interaction.response.send_message(final_screen)

    class SecondView(nextcord.ui.View):
        @nextcord.ui.button(label="CONFIRM", style=nextcord.ButtonStyle.danger)
        async def confirm(self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_modal(ConfirmModal())

        @nextcord.ui.button(label="ABORT MISSION", style=nextcord.ButtonStyle.success)
        async def abort(self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message("Protocol aborted.")

    class FirstView(nextcord.ui.View):
        @nextcord.ui.button(label="🚨 PROCEED 🚨", style=nextcord.ButtonStyle.danger)
        async def proceed(self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message(
                warning_two, view=SecondView()
            )

        @nextcord.ui.button(label="ABORT", style=nextcord.ButtonStyle.success)
        async def abort(self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message("Protocol aborted.")

    await interaction.response.send_message(warning_one, view=FirstView())



@bot.slash_command(
    name="omega-directive",
    description="Only activate in case of [REDACTED]",
    guild_ids=[GUILD_ID],
)
async def omega_directive(interaction: nextcord.Interaction):
    classified_role = interaction.guild.get_role(CLASSIFIED_ROLE_ID)
    if not classified_role:
        return await interaction.response.send_message(
            "Classified Clearance role not found.", ephemeral=True
        )
    if interaction.user.top_role.position < classified_role.position:
        return await interaction.response.send_message(
            "⛔ Classified clearance required.", ephemeral=True
        )

    screen_one = (
        "[ARCHIVE: OMEGA DIRECTIVE]\n"
        "System handshake in progress...\n"
        "> Validating Lazarus Key fragments\n"
        "> Checking post-Epsilon conditions\n"
        "> High Command clearance level: Level 5+\n"
        "Status: PENDING"
    )

    screen_two = (
        "[AUTHORIZATION REQUIRED]\n"
        "Insert both Lazarus Key fragments.\n"
        "- Primary Command Authentication: READY\n"
        "- Secondary Oversight Authentication: READY\n\n"
        "Note: System will abort if conditions fail.\n"
        "Continue with activation?"
    )

    final_screen = (
        "[OMEGA SEQUENCE INITIATED]\n"
        "This will begin post-Epsilon restoration procedures.\n"
        "System integrity will remain in Skeleton Mode until complete.\n\n"
        "T-minus 10 minutes to full activation.\n"
        "Abort option available until T-minus 1 minute."
    )

    class OmegaModal(nextcord.ui.Modal):
        def __init__(self):
            super().__init__(title="OMEGA AUTHORIZATION")
            self.fragment_one = nextcord.ui.TextInput(label="Primary Fragment")
            self.fragment_two = nextcord.ui.TextInput(label="Secondary Fragment")
            self.add_item(self.fragment_one)
            self.add_item(self.fragment_two)

        async def callback(self, modal_interaction: nextcord.Interaction):
            if modal_interaction.user != interaction.user:
                return await modal_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            if (
                self.fragment_one.value.strip() != OMEGA_KEY_FRAGMENT_1
                or self.fragment_two.value.strip() != OMEGA_KEY_FRAGMENT_2
            ):
                return await modal_interaction.response.send_message(
                    "Authorization failed.", ephemeral=True
                )
            await execute_omega_actions(modal_interaction.guild)
            await modal_interaction.response.send_message(final_screen)

    class SecondView(nextcord.ui.View):
        @nextcord.ui.button(label="ENTER KEYS", style=nextcord.ButtonStyle.danger)
        async def enter(self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_modal(OmegaModal())

        @nextcord.ui.button(label="ABORT", style=nextcord.ButtonStyle.success)
        async def abort(self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message("Omega directive aborted.")

    class FirstView(nextcord.ui.View):
        @nextcord.ui.button(label="CONTINUE", style=nextcord.ButtonStyle.primary)
        async def continue_btn(self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message(screen_two, view=SecondView())

        @nextcord.ui.button(label="ABORT", style=nextcord.ButtonStyle.success)
        async def abort(self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message("Omega directive aborted.")

    await interaction.response.send_message(screen_one, view=FirstView())


@bot.slash_command(
    name="omega-directive-test",
    description="Run diagnostics on Omega Directive codes.",
    guild_ids=[GUILD_ID],
)
async def omega_directive_test(interaction: nextcord.Interaction):
    """Slash command to verify Omega Directive key fragments."""

    directive = OmegaDirectiveTest()
    directive.register_code("OMEGA_AUTH", OMEGA_KEY_FRAGMENT_1)
    directive.register_code("OMEGA_LOCKDOWN", OMEGA_KEY_FRAGMENT_2)
    diagnostics = directive.test_codes(
        {
            "OMEGA_AUTH": OMEGA_KEY_FRAGMENT_1,
            "OMEGA_LOCKDOWN": OMEGA_KEY_FRAGMENT_2,
        }
    )
    result = "Omega Directive Test Results:\n" + "\n".join(
        f"  {line}" for line in diagnostics
    )
    await interaction.response.send_message(result)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set.")
    bot.run(TOKEN)
