import os
import random
import asyncio
import json
import io
import logging
import signal
import sys
import time
import threading
import tracemalloc
from tempfile import SpooledTemporaryFile
try:
    import psutil
except Exception:  # pragma: no cover - psutil may be unavailable
    psutil = None
from datetime import datetime, UTC, timedelta
from keepalive import start_keepalive
import nextcord
from nextcord import Embed
from nextcord.errors import LoginFailure
from nextcord.ext import commands, tasks

# Guard against running with an outdated Nextcord version that
# lacks support for the current Discord API. This helps provide
# a clear error message rather than silent failures where
# commands or interactions stop responding entirely.
_MIN_NEXTCORD_VERSION = (2, 6, 0)
_version_tuple = tuple(int(part) for part in nextcord.__version__.split("."))
if _version_tuple < _MIN_NEXTCORD_VERSION:
    min_version_str = ".".join(map(str, _MIN_NEXTCORD_VERSION))
    raise RuntimeError(
        f"Nextcord {min_version_str}+ is required; found {nextcord.__version__}. "
        "Please upgrade the 'nextcord' package."
    )

from constants import (
    TOKEN,
    GUILD_ID,
    MENU_CHANNEL_ID,
    ROOT_PREFIX,
    UPLOAD_CHANNEL_ID,
    LAZARUS_CHANNEL_ID,
    INTRO_TITLE,
    INTRO_DESC,
    REG_ARCHIVIST_TITLE,
    REG_ARCHIVIST_DESC,
    LEAD_ARCHIVIST_TITLE,
    LEAD_ARCHIVIST_DESC,
    HIGH_COMMAND_TITLE,
    HIGH_COMMAND_DESC,
    ARCHIVIST_ROLE_ID,
    HIGH_COMMAND_ROLE_ID,
    TRAINEE_ARCHIVIST_TITLE,
    TRAINEE_ARCHIVIST_DESC,
    TRAINEE_ROLE_ID,
    CLASSIFIED_ROLE_ID,
    SECTION_ZERO_CHANNEL_ID,
    EPSILON_LAUNCH_CODE,
    EPSILON_OWNER_CODE,
    EPSILON_XO_CODE,
    EPSILON_FLEET_CODE,
    OMEGA_KEY_FRAGMENT_1,
    OMEGA_KEY_FRAGMENT_2,
    OMEGA_BACKUP_PATH,
    OWNER_ROLE_ID,
    XO_ROLE_ID,
    FLEET_ADMIRAL_ROLE_ID,
)
from config import get_build_version
from storage_spaces import (
    ensure_dir,
    save_text,
    read_text,
    list_dir,
    read_json,
    delete_file,
)
from utils import DOSSIERS_DIR, list_categories
from dossier import attach_dossier_image, list_items_recursive
from async_utils import event_loop_watchdog
from acl import get_required_roles, grant_file_clearance, revoke_file_clearance
from views import CategorySelect, RootView, start_registration
from archivist import (
    handle_upload,
    ArchivistConsoleView,
    ArchivistLimitedConsoleView,
    ArchivistTraineeConsoleView,
    _is_archivist,
    _is_lead_archivist,
    _is_high_command,
    is_archive_locked,
    refresh_menus,
)
from roster import ROSTER_ROLES
from lazarus import LazarusAI
from operator_login import (
    list_operators,
    get_or_create_operator,
    detect_clearance,
    has_classified_clearance,
    set_clearance,
)
from section_zero import SectionZeroControlView, section_zero_embed
from archive_status import update_status_message
from async_utils import safe_handler

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

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("spectre")
logging.getLogger("nextcord.gateway").setLevel(logging.WARNING)
logging.getLogger("nextcord.http").setLevel(logging.WARNING)

tracemalloc.start()


def mem_report() -> None:
    snapshot = tracemalloc.take_snapshot()
    top = snapshot.statistics("lineno")
    for stat in top[:10]:
        logger.warning(stat)


async def monitor_memory() -> None:
    while True:
        mem_report()
        await asyncio.sleep(300)

if psutil:
    def _memory_watchdog() -> None:
        process = psutil.Process(os.getpid())
        while True:
            try:
                mem = process.memory_info().rss / 1024**3
                if mem > 7:  # warn if nearing 8 GB cap
                    logger.error("Spectre: Memory high: %.2f GB", mem)
            except Exception as exc:  # pragma: no cover - watchdog failures
                logger.warning("Memory watchdog failed: %s", exc)
            time.sleep(30)

    threading.Thread(target=_memory_watchdog, daemon=True).start()

_shutdown = False


def _sig(sig: int, frame) -> None:
    """Handle termination signals to allow graceful shutdown."""
    global _shutdown
    signame = signal.Signals(sig).name if isinstance(sig, int) else str(sig)
    logger.warning("Got %s, shutting down", signame)
    _shutdown = True
    # Attempt graceful bot shutdown if the loop is running.
    try:
        bot.loop.create_task(bot.close())
    except Exception:
        # If the bot loop isn't running yet, exiting is still fine.
        pass

HICCUP_CHANCE = float(os.getenv("HICCUP_CHANCE", "0"))
BACKUP_INTERVAL_HOURS = float(os.getenv("BACKUP_INTERVAL_HOURS", "0.5"))
LAZARUS_STATUS_INTERVAL = int(os.getenv("LAZARUS_STATUS_INTERVAL", "5"))

START_TIME = datetime.now(UTC)
lazarus_ai = LazarusAI(bot, LAZARUS_CHANNEL_ID, BACKUP_INTERVAL_HOURS, LAZARUS_STATUS_INTERVAL)
bot.add_cog(lazarus_ai)


def _autocomplete_items(category: str | None, partial: str) -> list[str]:
    if not category:
        return []
    try:
        items = list_items_recursive(category, max_items=25)
    except FileNotFoundError:
        return []
    partial = (partial or "").lower()
    return [i for i in items if i.lower().startswith(partial)][:25]


@bot.slash_command(
    name="set-file-image",
    description="Attach an image to a dossier page",
    guild_ids=[GUILD_ID],
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
    if not _is_archivist(interaction.user):
        return await interaction.response.send_message(" Archivist only.", ephemeral=True)
    if image.content_type and not image.content_type.startswith("image/"):
        return await interaction.response.send_message(" Attachment must be an image.", ephemeral=True)
    try:
        attach_dossier_image(category, item, page, image.url)
    except FileNotFoundError:
        return await interaction.response.send_message(" File not found.", ephemeral=True)
    except IndexError:
        return await interaction.response.send_message(" Invalid page number.", ephemeral=True)
    await interaction.response.send_message(" Image attached.", ephemeral=True)
    await log_action(
        f" {interaction.user.mention} attached IMAGE `{category}/{item}` page {page}."
    )

@set_file_image.on_autocomplete("item")
async def set_file_image_item_autocomplete(
    interaction: nextcord.Interaction, item: str
):
    # ``nextcord`` only provides the value being autocompleted as an
    # argument.  The selected category must be extracted from the raw
    # interaction payload so the lookup remains context-aware.
    category = None
    options = interaction.data.get("options", []) if interaction.data else []
    for opt in options:
        if opt.get("name") == "category":
            category = opt.get("value")
            break
    choices = _autocomplete_items(category, item)
    await interaction.response.send_autocomplete(choices)

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
    with SpooledTemporaryFile(max_size=1_000_000) as raw:
        with io.TextIOWrapper(raw, encoding="utf-8") as tmp:
            tmp.write("{")
            first = True

            def _recurse(pref: str) -> None:
                nonlocal first
                dirs, files = list_dir(pref, limit=10000)
                for fname, _ in files:
                    path = f"{pref}/{fname}" if pref else fname
                    try:
                        content = read_text(path)
                    except Exception:
                        continue
                    if not first:
                        tmp.write(",")
                    first = False
                    json.dump(path, tmp)
                    tmp.write(":")
                    json.dump(content, tmp)
                for d in dirs:
                    _recurse(f"{pref}/{d.strip('/')}")

            _recurse(ROOT_PREFIX)
            tmp.write("}")
            tmp.flush()
            raw.seek(0)

            ts = datetime.now(UTC)
            ensure_dir("backups")
            name = random.choice(GREEK_LETTERS)
            stamp = ts.strftime("%Y%m%dT%H%M%S")
            fname = f"backups/Backup protocol {name}-{stamp}.json"
            save_text(fname, raw, "application/json; charset=utf-8")
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


async def log_action(message: str, *, broadcast: bool = True) -> None:
    """Placeholder: logging disabled."""
    return


async def maybe_simulate_hiccup(interaction: nextcord.Interaction) -> bool:
    if random.random() < HICCUP_CHANCE:
        await interaction.response.send_message(
            " Node ECHO-04 failed to respond, rerouting… please hold.",
            ephemeral=True,
        )
        await asyncio.sleep(random.randint(3, 5))
        await interaction.edit_original_message(
            content=" Node ECHO-04 failed to respond, rerouting… please hold. Connection restored."
        )
        await log_action(
            " Node ECHO-04 failed to respond, rerouting… please hold. Connection restored."
        )
        return True
    return False


async def _backup_action():
    ts, fname = _backup_all()
    try:
        lazarus_ai.note_backup(ts)
    except Exception:
        pass
    await log_action(f" Backup saved to `{fname}`.", broadcast=False)
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


@tasks.loop(hours=BACKUP_INTERVAL_HOURS)
async def backup_loop():
    await _backup_action()


@bot.event
@safe_handler
async def on_ready():
    await log_action(f"SPECTRE online as {bot.user}", broadcast=False)
    if psutil:
        try:
            process = psutil.Process(os.getpid())
            logger.info("Memory: %s MB", process.memory_info().rss / 1024 ** 2)
        except Exception as exc:
            logger.warning("Memory check failed: %s", exc)
    ensure_dir(ROOT_PREFIX)
    for cat in ("missions", "personnel", "intelligence", "acl"):
        ensure_dir(f"{ROOT_PREFIX}/{cat}")
    bot.add_view(RootView())
    sz_view = SectionZeroControlView()
    bot.add_view(sz_view)
    guild = bot.get_guild(GUILD_ID)
    if guild:
        try:
            await refresh_menus(guild)
        except Exception:
            pass
    try:
        await update_status_message(bot)
    except Exception:
        pass
    sz_channel = bot.get_channel(SECTION_ZERO_CHANNEL_ID)
    if sz_channel and sz_channel.type == nextcord.ChannelType.text:
        try:
            existing = None
            if hasattr(sz_channel, "history"):
                async for msg in sz_channel.history(limit=100):
                    if (
                        msg.author == bot.user
                        and msg.embeds
                        and msg.embeds[0].title.startswith("\u26ab SECTION ZERO")
                    ):
                        existing = msg
                        break
            if existing:
                await existing.edit(embed=section_zero_embed(), view=sz_view)
            else:
                await sz_channel.send(embed=section_zero_embed(), view=sz_view)
        except Exception as e:
            logger.warning("Section Zero send failed: %s", e)
    else:
        logger.warning(
            "Invalid Section Zero channel ID: %s", SECTION_ZERO_CHANNEL_ID
        )
    if not backup_loop.is_running():
        backup_loop.start()
    lazarus_ai.start()


@bot.event
@safe_handler
async def on_disconnect() -> None:
    logger.warning("Bot disconnected, awaiting reconnect...")


@bot.event
@safe_handler
async def on_message(message: nextcord.Message):
    if message.author.bot:
        return
    if message.channel.id != UPLOAD_CHANNEL_ID:
        return
    await handle_upload(message)


@bot.slash_command(name="archivist", description="Open the Archivist Console", guild_ids=[GUILD_ID])
async def archivist_cmd(interaction: nextcord.Interaction):
    if not _is_archivist(interaction.user):
        return await interaction.response.send_message(" Archivist only.", ephemeral=True)
    sender = interaction.response.send_message
    if await maybe_simulate_hiccup(interaction):
        sender = interaction.followup.send
    is_high = _is_high_command(interaction.user)
    if is_archive_locked() and not is_high:
        return await sender(" Archive access locked.", ephemeral=True)
    is_lead = is_high or _is_lead_archivist(interaction.user)
    user_roles = {r.id for r in interaction.user.roles}
    is_trainee = (
        TRAINEE_ROLE_ID in user_roles and not is_lead and ARCHIVIST_ROLE_ID not in user_roles
    )
    view = (
        ArchivistConsoleView(interaction.user)
        if is_lead
        else ArchivistTraineeConsoleView(interaction.user)
        if is_trainee
        else ArchivistLimitedConsoleView(interaction.user)
    )
    if is_high:
        embed = Embed(
            title=HIGH_COMMAND_TITLE,
            description=HIGH_COMMAND_DESC,
            color=0xFF0000,
        )
    elif is_lead:
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


@bot.slash_command(name="show-id", description="Display operator ID cards", guild_ids=[GUILD_ID])
async def show_id(interaction: nextcord.Interaction):
    if has_classified_clearance(interaction.user):
        card = (
            "[GLACIER UNIT 7 — OPERATOR IDENTIFICATION CARD]\n"
            "Operator: [REDACTED]\n"
            "ID Number: [REDACTED]\n"
            "Clearance: [REDACTED]\n"
            "Status: [REDACTED]\n"
            "Session: [REDACTED]"
        )
        return await interaction.response.send_message(card)

    op = next(
        (o for o in list_operators() if o.user_id == interaction.user.id and o.password_hash),
        None,
    )
    if not op:
        return await interaction.response.send_message(
            "No operator ID on file. Use /create-id to register.", ephemeral=True
        )

    member = getattr(interaction.guild, "get_member", lambda x: None)(op.user_id) or interaction.user
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    card = (
        "[GLACIER UNIT 7 — OPERATOR IDENTIFICATION CARD]\n"
        f"Operator: {member.mention}\n"
        f"ID Number: {op.id_code}\n"
        f"Clearance: Level-{op.clearance}\n"
        "Status: ACTIVE\n"
        f"Session: {ts}"
    )
    await interaction.response.send_message(card)


@bot.slash_command(
    name="create-id",
    description="Begin operator ID registration",
    guild_ids=[GUILD_ID],
)
async def create_id(interaction: nextcord.Interaction):
    if has_classified_clearance(interaction.user):
        return await interaction.response.send_message(
            "Classified operatives are exempt from ID registration.", ephemeral=True
        )
    level = detect_clearance(interaction.user)

    op = get_or_create_operator(interaction.user.id)
    if op.clearance != level:
        set_clearance(interaction.user.id, level)
    if op.password_hash:
        return await interaction.response.send_message(
            "Operator ID already exists.", ephemeral=True
        )
    await start_registration(interaction, op, interaction.user)


@bot.slash_command(name="request", description="Submit requests", guild_ids=[GUILD_ID])
async def request_root(interaction: nextcord.Interaction):
    pass




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
    await log_action(" Protocol EPSILON purge executed.")


async def execute_omega_actions(guild: nextcord.Guild) -> None:
    """Restore system state from the hidden Omega backup."""

    try:
        _restore_backup(OMEGA_BACKUP_PATH)
        await log_action(" Omega Directive restoration executed.")
    except Exception as e:
        await log_action(f" Omega restore error: {e}")

@bot.slash_command(
    name="protocol-epsilon",
    description="WARNING ONLY ACTIVATE UNDER GUIDANCE OF FILE EPSILON",
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
            " Classified clearance required.", ephemeral=True
        )

    role_ping = (
        f"<@&{OWNER_ROLE_ID}> <@&{XO_ROLE_ID}> <@&{FLEET_ADMIRAL_ROLE_ID}>"
    )

    warning_one = (
        f"{role_ping}\n"
        "[ACCESS NODE: EPSILON]\n"
        "> Command Detected: /protocol-epsilon\n"
        "> Warning: This action will trigger FINAL CONTINGENCY PROTOCOL.\n"
        "──────────────────────────────\n"
        "  WARNING EPSILON IS A NO-FAIL PROTOCOL\n"
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
        " ALERT  PROTOCOL EPSILON IS NOW ACTIVE \n"
        "Glacier HQ will enter full lockdown in T-60 seconds."
    )

    class OwnerModal(nextcord.ui.Modal):
        def __init__(self, parent_view: nextcord.ui.View):
            super().__init__(title="OWNER AUTHORIZATION")
            self.parent_view = parent_view
            self.code = nextcord.ui.TextInput(label="Owner code")
            self.add_item(self.code)

        async def callback(self, modal_interaction: nextcord.Interaction):
            if self.code.value.strip() != EPSILON_OWNER_CODE:
                return await modal_interaction.response.send_message(
                    "Authorization failed.", ephemeral=True
                )
            self.parent_view.owner_confirmed = True
            # Disable the Owner button and warn the channel
            for child in self.parent_view.children:
                if isinstance(child, nextcord.ui.Button) and child.label == "OWNER CONFIRM":
                    child.disabled = True
                    break
            warning_msg = (
                f"\U0001F6A8{modal_interaction.user.mention} ENTERED THEIR ACTIVATION CODE\U0001F6A8"
            )
            await log_action(warning_msg)
            try:
                await modal_interaction.channel.send(warning_msg)
            except Exception:
                pass
            await modal_interaction.response.send_message(
                "Owner authorization accepted.", ephemeral=True
            )
            try:
                await modal_interaction.message.edit(view=self.parent_view)
            except Exception:
                pass

    class XOModal(nextcord.ui.Modal):
        def __init__(self, parent_view: nextcord.ui.View):
            super().__init__(title="XO AUTHORIZATION")
            self.parent_view = parent_view
            self.code = nextcord.ui.TextInput(label="XO code")
            self.add_item(self.code)

        async def callback(self, modal_interaction: nextcord.Interaction):
            if self.code.value.strip() != EPSILON_XO_CODE:
                return await modal_interaction.response.send_message(
                    "Authorization failed.", ephemeral=True
                )
            self.parent_view.xo_confirmed = True
            for child in self.parent_view.children:
                if isinstance(child, nextcord.ui.Button) and child.label == "XO CONFIRM":
                    child.disabled = True
                    break
            warning_msg = (
                f"\U0001F6A8{modal_interaction.user.mention} ENTERED THEIR ACTIVATION CODE\U0001F6A8"
            )
            await log_action(warning_msg)
            try:
                await modal_interaction.channel.send(warning_msg)
            except Exception:
                pass
            await modal_interaction.response.send_message(
                "XO authorization accepted.", ephemeral=True
            )
            try:
                await modal_interaction.message.edit(view=self.parent_view)
            except Exception:
                pass

    class FleetModal(nextcord.ui.Modal):
        def __init__(self, parent_view: nextcord.ui.View):
            super().__init__(title="FLEET ADMIRAL AUTHORIZATION")
            self.parent_view = parent_view
            self.code = nextcord.ui.TextInput(label="Fleet Admiral code")
            self.add_item(self.code)

        async def callback(self, modal_interaction: nextcord.Interaction):
            if self.code.value.strip() != EPSILON_FLEET_CODE:
                return await modal_interaction.response.send_message(
                    "Authorization failed.", ephemeral=True
                )
            self.parent_view.fleet_confirmed = True
            for child in self.parent_view.children:
                if isinstance(child, nextcord.ui.Button) and child.label == "FLEET CONFIRM":
                    child.disabled = True
                    break
            warning_msg = (
                f"\U0001F6A8{modal_interaction.user.mention} ENTERED THEIR ACTIVATION CODE\U0001F6A8"
            )
            await log_action(warning_msg)
            try:
                await modal_interaction.channel.send(warning_msg)
            except Exception:
                pass
            await modal_interaction.response.send_message(
                "Fleet Admiral authorization accepted.", ephemeral=True
            )
            try:
                await modal_interaction.message.edit(view=self.parent_view)
            except Exception:
                pass

    class FinalApprovalView(nextcord.ui.View):
        def __init__(self, initiator_id: int):
            super().__init__()
            self.initiator_id = initiator_id
            self.owner_confirmed = False
            self.xo_confirmed = False
            self.fleet_confirmed = False
            self.message: nextcord.Message | None = None

        @nextcord.ui.button(label="OWNER CONFIRM", style=nextcord.ButtonStyle.primary)
        async def owner(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if OWNER_ROLE_ID not in [r.id for r in getattr(button_interaction.user, "roles", [])]:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_modal(OwnerModal(self))

        @nextcord.ui.button(label="XO CONFIRM", style=nextcord.ButtonStyle.primary)
        async def xo(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if XO_ROLE_ID not in [r.id for r in getattr(button_interaction.user, "roles", [])]:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_modal(XOModal(self))

        @nextcord.ui.button(label="FLEET CONFIRM", style=nextcord.ButtonStyle.primary)
        async def fleet(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if FLEET_ADMIRAL_ROLE_ID not in [
                r.id for r in getattr(button_interaction.user, "roles", [])
            ]:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_modal(FleetModal(self))

        @nextcord.ui.button(label="LAUNCH", style=nextcord.ButtonStyle.danger)
        async def launch(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if button_interaction.user.id != self.initiator_id:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            if not (
                self.owner_confirmed
                and self.xo_confirmed
                and self.fleet_confirmed
            ):
                return await button_interaction.response.send_message(
                    "Awaiting all confirmations.", ephemeral=True
                )
            await execute_epsilon_actions(button_interaction.guild, classified_role)
            await button_interaction.response.send_message(final_screen)

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
            view = FinalApprovalView(interaction.user.id)
            await modal_interaction.response.send_message(
                "Primary authorization accepted. Awaiting Owner, XO, and Fleet Admiral confirmations.",
                view=view,
            )
            try:
                view.message = await modal_interaction.original_message()
            except Exception:
                pass

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
        @nextcord.ui.button(label=" PROCEED ", style=nextcord.ButtonStyle.danger)
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

    await interaction.response.send_message(
        warning_one, view=FirstView(), allowed_mentions=nextcord.AllowedMentions(roles=True)
    )



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
            " Classified clearance required.", ephemeral=True
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



if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    if not TOKEN:
        logger.error("DISCORD_TOKEN is not set.")
        raise RuntimeError("DISCORD_TOKEN is not set.")

    async def run_bot() -> None:
        loop = asyncio.get_running_loop()

        def _handle_exception(loop: asyncio.AbstractEventLoop, context: dict) -> None:
            exception = context.get("exception")
            if exception:
                logger.error("Unhandled exception in event loop", exc_info=exception)
            else:
                logger.error("Unhandled event loop error: %s", context)

        loop.set_exception_handler(_handle_exception)

        asyncio.create_task(event_loop_watchdog(loop, logger=logger))

        # --- Keepalive HTTP server ---
        start_keepalive()
        asyncio.create_task(monitor_memory())

        backoff = 1
        while True:
            try:
                logger.info("Attempting to start Discord bot")
                await bot.start(TOKEN)
            except LoginFailure as exc:
                logger.error("Failed to authenticate with Discord: %s", exc)
                return
            except KeyboardInterrupt:
                logger.info("Shutdown requested, closing bot")
                await bot.close()
                break
            except Exception as exc:  # pragma: no cover - network/Discord issues
                logger.exception(
                    "Bot connection failed, retrying in %s seconds", backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            else:
                if _shutdown:
                    logger.info("Shutdown signal received, exiting run loop")
                    break
                backoff = 1
                logger.warning(
                    "Bot stopped unexpectedly, restarting in %s seconds", backoff
                )
                await asyncio.sleep(backoff)

    while True:
        try:
            logger.info("Boot sequence initiated")
            asyncio.run(run_bot())
            break
        except KeyboardInterrupt:  # pragma: no cover - manual shutdown
            logger.info("Shutdown requested, exiting")
            break
        except Exception:
            logger.exception(
                "Unhandled exception during bot startup, restarting in 5 seconds"
            )
            time.sleep(5)
