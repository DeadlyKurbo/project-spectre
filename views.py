import io
import random
import string
import asyncio
import re
import time
from typing import Dict, Set

import nextcord
from nextcord import (
    Embed,
    SelectOption,
    ButtonStyle,
    InteractionResponded,
    TextInputStyle,
)
from nextcord.ui import View, Select, Button, Modal, TextInput

from annotations import list_file_annotations

from acl import grant_temp_clearance, check_temp_clearance

from dossier import (
    list_categories,
    list_items_recursive,
    _find_existing_item_key,
    read_json,
    read_text,
)
from constants import (
    INTRO_TITLE,
    INTRO_DESC,
    CLEARANCE_REQUESTS_CHANNEL_ID,
    LEAD_ARCHIVIST_ROLE_ID,
    LEAD_NOTIFICATION_CHANNEL_ID,
    SECURITY_LOG_CHANNEL_ID,
    REPORT_REPLY_CHANNEL_ID,
    CONTENT_MAX_LENGTH,
    PAGE_SEPARATOR,
    CATEGORY_ORDER,
    CATEGORY_STYLES,
)

from operator_login import (
    get_or_create_operator,
    verify_password,
    set_password,
    set_clearance,
    get_allowed_categories,
    generate_session_id,
    update_id_code,
    list_operators,
    detect_clearance,
    detect_rank,
    has_classified_clearance,
    has_active_session,
    touch_session,
)

LABELS = {slug: label for slug, label in CATEGORY_ORDER}

# ===== RP System Alerts =====
ALERT_MESSAGES = [
    "Archive Node Delta not responding – rerouting traffic…",
    "Quantum indexer misaligned – initiating recalibration…",
    "Remote vault link degraded – seeking alternative route…",
]

# Cache of last successful access sequence per user
_last_verified: Dict[int, float] = {}

# Users currently operating under clearance bypass
_bypass_sessions: Set[int] = set()

# Timestamp of last ID change request per user
_last_id_change_request: Dict[int, float] = {}


def _user_mention(interaction: nextcord.Interaction) -> str:
    """Return a display name for logging, redacting bypass users."""
    return "[REDACTED]" if interaction.user.id in _bypass_sessions else interaction.user.mention


async def _clear_bypass(user_id: int, delay: int = 600) -> None:
    """Remove ``user_id`` from bypass sessions after ``delay`` seconds."""
    await asyncio.sleep(delay)
    _bypass_sessions.discard(user_id)


async def maybe_system_alert(
    interaction: nextcord.Interaction, on_fix=None
) -> bool:
    """Randomly display a fatal system error before continuing."""
    if random.random() < 0.02:
        embed = Embed(
            title="⚠️ Fatal System Error",
            description=random.choice(ALERT_MESSAGES),
            color=0xFF0000,
        )
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except InteractionResponded:
            await interaction.followup.send(embed=embed, ephemeral=True)
        await asyncio.sleep(2)
        if on_fix:
            await on_fix(interaction)
            return True
    return False


async def run_access_sequence(
    interaction: nextcord.Interaction,
    authorized: bool,
    case_ref: str,
    use_followup: bool = False,
    request_view: View | None = None,
) -> None:
    """Display staged security checks before revealing access result."""
    msg1 = (
        "🛰️ Establishing secure uplink to Glacier Unit-7 Mainframe…\n"
        "Monitoring operator entry point for unauthorized signals."
    )
    msg2 = (
        "[MAINFRAME STATUS: ONLINE]\n"
        "> Initiating access protocols…\n"
        "> Scanning operator ID for anomalies…\n"
        "> Tracing connection source: [ENCRYPTED]\n"
        "> Cross-referencing watchlist database…"
    )
    msg3 = (
        "> Threat level: LOW\n"
        "> Operator identity confirmed.\n"
        "> Activity logs archived for GU7 Security Command."
    )
    if use_followup:
        message = await interaction.followup.send(msg1, ephemeral=True)
    else:
        await interaction.response.send_message(msg1, ephemeral=True)
        orig = getattr(interaction, "original_message", None)
        if orig:
            message = await orig()
        else:
            class _Dummy:
                async def edit(self, *a, **k):
                    pass

            message = _Dummy()
    await asyncio.sleep(random.randint(2, 3))
    await message.edit(content=msg2)
    await asyncio.sleep(random.randint(2, 3))
    await message.edit(content=msg3)
    await asyncio.sleep(random.randint(2, 3))
    if authorized:
        final = (
            "> ACCESS NODE UNLOCKED\n"
            "> Forwarding operator to secure file interface…"
        )
        await message.edit(content=final)
    else:
        final = (
            "> ACCESS DENIED\n"
            "> Operator ID flagged for unauthorized activity.\n"
            f"> Incident logged under case reference: {case_ref}\n\n"
            "Would you like to request access to this file?"
        )
        await message.edit(content=final, view=request_view)


async def start_registration(
    interaction: nextcord.Interaction, operator, member: nextcord.Member
) -> None:
    session_key = (
        "REG-"
        + f"{random.randint(1000, 9999)}-"
        + "".join(random.choices(string.ascii_uppercase, k=2))
    )
    await interaction.response.send_message(
        "Check your DMs to design your Operator ID.", ephemeral=True
    )
    try:
        message = await member.send("Initializing... [█▒▒▒▒▒▒▒▒▒]")
    except Exception:
        # Fallback to the original interaction message if DM is disabled
        orig = getattr(interaction, "original_message", None)
        if orig:
            message = await orig()
        else:
            class _Dummy:
                async def edit(self, *a, **k):
                    pass

            message = _Dummy()
    await asyncio.sleep(1)
    await message.edit(content="Preparing interface... [████▒▒▒▒▒▒]")
    await asyncio.sleep(1)
    await message.edit(content="Complete. [██████████]")
    await asyncio.sleep(1)
    desc = (
        "Welcome, Operative.\n"
        "Your credentials were not found in the Archive.\n"
        "Follow the steps below to complete your registration:\n\n"
        "Step 1 – Choose Operator ID\n"
        "Reply to this DM with your desired identification number.\n"
        "Requirements: 4-20 characters using letters, numbers, or hyphens.\n"
        "ID must be unique.\n\n"
        f"Session Key: {session_key}\n"
    )
    embed = Embed(
        title="[PERSONNEL REGISTRATION TERMINAL]",
        description=desc,
        color=0x00FFCC,
    )
    await message.edit(content=None, embed=embed)

    channel = getattr(message, "channel", None)
    client = getattr(interaction, "client", None)
    if not channel or not client:
        return

    def check(m: nextcord.Message) -> bool:
        return m.author == member and m.channel == channel

    while True:
        try:
            reply = await client.wait_for("message", timeout=120, check=check)
        except asyncio.TimeoutError:
            await channel.send("⛔ Registration timed out. Please restart the process.")
            return
        desired = reply.content.strip().upper()
        if not re.match(r"^[A-Z0-9\-]{4,20}$", desired):
            await channel.send(
                "Invalid ID format. Use 4-20 characters with letters, numbers, or hyphens."
            )
            continue
        if any(op.id_code.upper() == desired for op in list_operators()):
            await channel.send("ID already in use. Please try another.")
            continue
        update_id_code(operator.user_id, desired)
        break

    view = View(timeout=None)
    btn = Button(label="Set Password", style=ButtonStyle.primary)

    async def open_modal(inter: nextcord.Interaction):
        await inter.response.send_modal(
            RegistrationModal(operator, member, session_key)
        )

    btn.callback = open_modal
    view.add_item(btn)
    await channel.send("✅ Operator ID set. Click the button below to finalize registration.", view=view)




class ClearanceDecisionView(View):
    """Buttons allowing Lead Archivists to grant or deny requests."""

    def __init__(self, requester: nextcord.Member, category: str, item: str):
        super().__init__(timeout=None)
        self.requester = requester
        self.category = category
        self.item = item

        grant_btn = Button(label="Grant", style=ButtonStyle.success)
        grant_btn.callback = self.grant
        self.add_item(grant_btn)

        deny_btn = Button(label="Deny", style=ButtonStyle.danger)
        deny_btn.callback = self.deny
        self.add_item(deny_btn)

    async def _check_role(self, interaction: nextcord.Interaction) -> bool:
        if LEAD_ARCHIVIST_ROLE_ID and LEAD_ARCHIVIST_ROLE_ID not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message(
                "⛔ Lead Archivist only.", ephemeral=True
            )
            return False
        return True

    async def grant(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        import main

        grant_temp_clearance(self.category, self.item, self.requester.id)
        msg = (
            f"✅ {self.requester.mention} your request for "
            f"`{self.category}/{self.item}` was approved by {interaction.user.mention}. "
            "You have 10 minutes to access the file."
        )
        await interaction.response.send_message(msg)
        await main.log_action(
            f"✅ {_user_mention(interaction)} granted {self.requester.mention} access to `{self.category}/{self.item}`."
        )
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    async def deny(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        import main

        msg = (
            f"❌ {self.requester.mention} your request for "
            f"`{self.category}/{self.item}` was denied by {interaction.user.mention}."
        )
        await interaction.response.send_message(msg)
        await main.log_action(
            f"❌ {_user_mention(interaction)} denied {self.requester.mention} access to `{self.category}/{self.item}`."
        )
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)


class IdChangeDecisionView(View):
    """Buttons allowing Lead Archivists to approve or deny ID changes."""

    def __init__(self, requester: nextcord.Member, new_id: str):
        super().__init__(timeout=None)
        self.requester = requester
        self.new_id = new_id

        approve = Button(label="Approve", style=ButtonStyle.success)
        approve.callback = self.approve
        self.add_item(approve)

        deny = Button(label="Deny", style=ButtonStyle.danger)
        deny.callback = self.deny
        self.add_item(deny)

    async def _check_role(self, interaction: nextcord.Interaction) -> bool:
        if LEAD_ARCHIVIST_ROLE_ID and LEAD_ARCHIVIST_ROLE_ID not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message(
                "⛔ Lead Archivist only.", ephemeral=True
            )
            return False
        return True

    async def approve(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        import main

        update_id_code(self.requester.id, self.new_id)
        msg = (
            f"✅ {self.requester.mention}'s ID updated to `{self.new_id}` by {interaction.user.mention}."
        )
        await interaction.response.send_message(msg)
        await main.log_action(
            f"✅ {_user_mention(interaction)} approved ID change for {self.requester.mention} to `{self.new_id}`."
        )
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    async def deny(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        import main

        msg = (
            f"❌ {self.requester.mention}'s ID change request was denied by {interaction.user.mention}."
        )
        await interaction.response.send_message(msg)
        await main.log_action(
            f"❌ {_user_mention(interaction)} denied ID change for {self.requester.mention} requesting `{self.new_id}`."
        )
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)


class ClearanceRequestView(View):
    """Button view allowing a user to request dossier clearance."""

    def __init__(self, user: nextcord.Member, category: str, item: str):
        super().__init__(timeout=180)
        self.user = user
        self.category = category
        self.item = item
        btn = Button(
            label="Request Clearance",
            style=ButtonStyle.primary,
            custom_id="req_clearance_v1",
        )
        btn.callback = self.submit
        self.add_item(btn)

    async def submit(self, interaction: nextcord.Interaction):
        from dossier import _find_existing_item_key, read_text
        import main

        channel = None
        if CLEARANCE_REQUESTS_CHANNEL_ID:
            channel = interaction.guild.get_channel(CLEARANCE_REQUESTS_CHANNEL_ID)
            if not channel:
                try:
                    channel = await interaction.client.fetch_channel(
                        CLEARANCE_REQUESTS_CHANNEL_ID
                    )
                except Exception:
                    channel = None

        mention = (
            f"<@&{LEAD_ARCHIVIST_ROLE_ID}>" if LEAD_ARCHIVIST_ROLE_ID else "Lead Archivists"
        )

        file = None
        try:
            found = _find_existing_item_key("personnel", str(self.user.id))
            if found:
                path, ext = found
                content = read_text(path)
                file = nextcord.File(
                    io.BytesIO(content.encode("utf-8")),
                    filename=f"dossier_{self.user.id}{ext}",
                )
        except Exception:
            file = None

        if channel:
            msg = (
                f"{mention} {self.user.mention} requests clearance for "
                f"`{self.category}/{self.item}`."
            )
            try:
                view = ClearanceDecisionView(self.user, self.category, self.item)
                if file:
                    await channel.send(msg, file=file, view=view)
                else:
                    await channel.send(msg + " (no dossier found)", view=view)
            except Exception:
                pass

        await interaction.response.send_message(
            "📨 Clearance request sent.", ephemeral=True
        )
        mention = (
            "[REDACTED]" if self.user.id in _bypass_sessions else self.user.mention
        )
        await main.log_action(
            f"✉️ {mention} requested clearance for `{self.category}/{self.item}`."
        )


class FileErrorReportModal(Modal):
    def __init__(self, category: str, item: str, message_link: str, reporter: nextcord.Member):
        super().__init__(title="Report File Error")
        self.category = category
        self.item = item
        self.message_link = message_link
        options = [
            "Broken Link",
            "Outdated Info",
            "Formatting Issue",
            "Clearance Mismatch",
            "Other",
        ]
        self.error_type = TextInput(
            label="Error Type",
            placeholder=", ".join(options),
            min_length=1,
            max_length=100,
        )
        self.details = TextInput(
            label="Details",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=CONTENT_MAX_LENGTH,
        )
        self.contact = TextInput(
            label="Optional Contact",
            default_value=str(reporter),
            required=False,
            max_length=200,
        )
        self.add_item(self.error_type)
        self.add_item(self.details)
        self.add_item(self.contact)

    async def callback(self, interaction: nextcord.Interaction):
        channel = None
        if LEAD_NOTIFICATION_CHANNEL_ID:
            channel = interaction.guild.get_channel(LEAD_NOTIFICATION_CHANNEL_ID)
            if not channel:
                try:
                    channel = await interaction.client.fetch_channel(LEAD_NOTIFICATION_CHANNEL_ID)
                except Exception:
                    channel = None
        error_type = self.error_type.value.strip() or "Unspecified"
        description = self.details.value.strip()
        contact = self.contact.value.strip() if self.contact.value else str(interaction.user)
        from datetime import datetime, UTC

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        file_path = f"{self.category}/{self.item}"
        msg = (
            "⚠️ File Error Report\n"
            f"File: `{file_path}`\n"
            f"Link: {self.message_link}\n"
            f"Reporter: {interaction.user.mention}\n"
            f"Error Type: {error_type}\n"
            f"Timestamp: {timestamp}\n"
            f"Description: {description}\n"
            f"Contact: {contact}"
        )
        if channel:
            try:
                await channel.send(msg)
            except Exception:
                pass
        await interaction.response.send_message(
            "Report logged. Lead Archivist will review.", ephemeral=True
        )
        import main

        await main.log_action(
            f"⚠️ {_user_mention(interaction)} reported error '{error_type}' on `{file_path}`: {description}"
        )


class CategorySelect(Select):
    def __init__(
        self,
        member: nextcord.Member | None = None,
        categories: list[str] | None = None,
    ):
        self.member = member
        self.category = None
        self._cache: dict[str, list[str]] = {}

        cats = categories or list_categories()
        options: list[SelectOption] = []
        for c in cats:
            items = self._filter_items(c)
            if not items:
                continue
            self._cache[c] = items
            emoji, _ = CATEGORY_STYLES.get(c, (None, None))
            label = LABELS.get(c, c.replace("_", " ").title())
            if emoji:
                label = f"{emoji} {label}"
            options.append(SelectOption(label=label, value=c))
            if len(options) >= 25:
                break
        super().__init__(
            placeholder="Select a category…",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="cat_select_v4",
        )

    def _filter_items(self, category: str) -> list[str]:
        """Return all dossier items for ``category``.

        Clearance checks are handled when an item is opened, so the listing
        itself exposes every file name.
        """

        return list_items_recursive(category)

    def build_item_list_view(self, category: str):
        items = self._cache.get(category)
        if items is None:
            items = self._filter_items(category)
            self._cache[category] = items
        emoji, color = CATEGORY_STYLES.get(category, (None, 0x00FFCC))
        title = LABELS.get(category, category.replace("_", " ").title())
        if emoji:
            title = f"{emoji} {title}"
        embed = Embed(
            title=title,
            description=("Select a file…" if items else "_No files._"),
            color=color,
        )
        view = View(timeout=None)
        if items:
            select_item = Select(
                placeholder="Select a file…",
                options=[SelectOption(label=i, value=i) for i in items[:25]],
                min_values=1,
                max_values=1,
                custom_id="cat_item_select_v4",
            )
            select_item.callback = self.on_item
            view.add_item(select_item)
        return embed, view

    async def callback(self, interaction: nextcord.Interaction):
        self.category = self.values[0]
        embed, view = self.build_item_list_view(self.category)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_item(self, interaction: nextcord.Interaction):
        item_rel_base = interaction.data["values"][0]

        async def resume(inter: nextcord.Interaction):
            await self._show_with_sequence(inter, item_rel_base, use_followup=True)

        if await maybe_system_alert(interaction, on_fix=resume):
            return
        await self._show_with_sequence(interaction, item_rel_base)

    async def _show_with_sequence(
        self,
        interaction: nextcord.Interaction,
        item_rel_base: str,
        use_followup: bool = False,
    ) -> None:
        category = self.category or list_categories()[0]
        found = _find_existing_item_key(category, item_rel_base)
        if not found:
            sender = interaction.followup.send if use_followup else interaction.response.send_message
            await sender("❌ File not found.", ephemeral=True)
            return
        _key, ext = found

        import main
        required = main.get_required_roles(category, item_rel_base)
        user_roles = {r.id for r in interaction.user.roles}
        has_temp = check_temp_clearance(
            interaction.user.id, category, item_rel_base
        )
        authorized = (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
            or (user_roles & required)
            or has_temp
        )
        case_ref = f"GU7-SC-{random.randint(100,999)}"
        now = time.time()
        user_id = interaction.user.id
        request_view = None
        if not authorized:
            request_view = ClearanceRequestView(interaction.user, category, item_rel_base)
        if not (authorized and now - _last_verified.get(user_id, 0) < 600):
            if authorized:
                # mark early to prevent concurrent verification sequences
                _last_verified[user_id] = now
            try:
                await run_access_sequence(
                    interaction,
                    authorized,
                    case_ref,
                    use_followup,
                    request_view=request_view,
                )
            except Exception:
                if authorized:
                    _last_verified.pop(user_id, None)
                raise
            if authorized:
                _last_verified[user_id] = time.time()
            else:
                _last_verified.pop(user_id, None)
        if not authorized:
            await main.log_action(
                f"🚫 {_user_mention(interaction)} attempted to access `{category}/{item_rel_base}{ext}` without clearance."
            )
            channel = interaction.guild.get_channel(SECURITY_LOG_CHANNEL_ID)
            if not channel:
                try:
                    channel = await interaction.client.fetch_channel(SECURITY_LOG_CHANNEL_ID)
                except Exception:
                    channel = None
            if channel:
                try:
                    await channel.send(
                        f"Unauthorized access attempt by {_user_mention(interaction)} on `{category}/{item_rel_base}{ext}`. Case {case_ref}"
                    )
                except Exception:
                    pass
            return
        done = (
            interaction.response.is_done()
            if hasattr(interaction.response, "is_done")
            else False
        )
        await self._show_item(
            interaction,
            item_rel_base,
            use_followup=done,
        )

    async def _show_item(
        self,
        interaction: nextcord.Interaction,
        item_rel_base: str,
        use_followup: bool = False,
    ):
        category = self.category or list_categories()[0]

        found = _find_existing_item_key(category, item_rel_base)
        if not found:
            return await interaction.response.send_message("❌ File not found.", ephemeral=True)
        key, ext = found

        import main
        required = main.get_required_roles(category, item_rel_base)
        user_roles = {r.id for r in interaction.user.roles}
        has_temp = check_temp_clearance(
            interaction.user.id, category, item_rel_base
        )
        if not (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
            or (user_roles & required)
            or has_temp
        ):
            import main
            await main.log_action(
                f"🚫 {_user_mention(interaction)} attempted to access `{category}/{item_rel_base}{ext}` without clearance."
            )
            view = ClearanceRequestView(interaction.user, category, item_rel_base)
            sender = (
                interaction.followup.send if use_followup else interaction.response.send_message
            )
            return await sender(
                "⛔ Insufficient clearance.", ephemeral=True, view=view
            )

        import main
        await main.log_action(
            f"📄 {_user_mention(interaction)} accessed `{category}/{item_rel_base}{ext}`."
        )

        emoji, color = CATEGORY_STYLES.get(category, (None, 0x00FFCC))
        item_title = item_rel_base.split('/')[-1].replace('_', ' ').title()
        cat_title = LABELS.get(category, category.replace('_', ' ').title())
        title = f"{item_title} — {cat_title}"
        if emoji:
            title = f"{emoji} {title}"
        rpt = Embed(title=title, color=color)
        roles_needed = [f"<@&{str(r)}>" for r in required] if required else ["None (public)"]
        rpt.add_field(name="🔐 Required Clearance", value=", ".join(roles_needed), inline=False)

        page_index = 0
        pages = None
        try:
            data = read_json(key)
            if isinstance(data, dict):
                if "summary" in data and data["summary"]:
                    rpt.description = str(data["summary"])
                for k, v in data.items():
                    if k == "summary":
                        continue
                    if k == "pdf_link":
                        rpt.add_field(name="📎 Attached File", value=f"[Open]({v})", inline=False)
                    else:
                        val = str(v)
                        if len(val) > 1024:
                            val = val[:1021] + "..."
                        rpt.add_field(
                            name=k.replace("_", " ").title(),
                            value=val,
                            inline=False,
                        )
            else:
                raise ValueError("JSON root not dict")
        except Exception:
            try:
                blob = read_text(key)
            except Exception:
                sender = (
                    interaction.followup.send
                    if use_followup
                    else interaction.response.send_message
                )
                return await sender("❌ Could not read file.", ephemeral=True)
            if PAGE_SEPARATOR in blob:
                pages = blob.split(PAGE_SEPARATOR)
            else:
                pages = [blob[i : i + 1000] for i in range(0, len(blob), 1000)]

            def format_page(idx: int) -> str:
                show = pages[idx]
                if re.search(r"https?://", show):
                    val = show
                else:
                    val = f"```txt\n{show}\n```"
                if len(val) > 1024:
                    val = val[:1021] + "..."
                return val

            field_name = (
                "Contents"
                if len(pages) == 1
                else f"Contents (page 1/{len(pages)})"
            )
            rpt.add_field(name=field_name, value=format_page(page_index), inline=False)

        notes = list_file_annotations(category, item_rel_base)
        if notes:
            summary = "\n".join(notes)
            if len(summary) > 1024:
                summary = summary[-1024:]
            rpt.add_field(name="🖊️ Archivist Notes", value=summary, inline=False)

        items = list_items_recursive(category)
        view = View(timeout=None)

        if pages and len(pages) > 1:
            prev_btn = Button(
                label="Previous Page",
                style=ButtonStyle.secondary,
                custom_id="prev_page_v1",
            )
            next_btn = Button(
                label="Next Page",
                style=ButtonStyle.primary,
                custom_id="next_page_v1",
            )
            prev_btn.disabled = True

            async def change_page(inter: nextcord.Interaction, delta: int):
                nonlocal page_index
                page_index += delta
                prev_btn.disabled = page_index == 0
                next_btn.disabled = page_index >= len(pages) - 1
                name = f"Contents (page {page_index + 1}/{len(pages)})"
                rpt.set_field_at(
                    1,
                    name=name,
                    value=format_page(page_index),
                    inline=False,
                )
                await inter.response.edit_message(embed=rpt, view=view)

            async def go_prev(inter: nextcord.Interaction):
                await change_page(inter, -1)

            async def go_next(inter: nextcord.Interaction):
                await change_page(inter, 1)

            prev_btn.callback = go_prev
            next_btn.callback = go_next
            view.add_item(prev_btn)
            view.add_item(next_btn)

        select_another = Select(
            placeholder="Select another item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="cat_item_select_again_v3",
        )
        select_another.callback = self.on_item
        view.add_item(select_another)

        file_types = sorted({i.split("/", 1)[0] for i in items if "/" in i})
        if file_types:
            select_type = Select(
                placeholder="Select a file type…",
                options=[SelectOption(label=t, value=t) for t in file_types[:25]],
                min_values=1,
                max_values=1,
                custom_id="cat_type_select_v1",
            )

            async def on_type(inter2: nextcord.Interaction):
                ft = inter2.data["values"][0]
                filtered = [i for i in items if i.startswith(ft + "/")]
                embed2 = Embed(
                    title=f"Archive: {category.replace('_',' ').title()} — {ft.replace('_',' ').title()}",
                    description=("Select an item…" if filtered else "_No files in this type._"),
                    color=0x00FFCC,
                )
                view2 = View(timeout=None)
                if filtered:
                    opts = [
                        SelectOption(label=i[len(ft) + 1 :], value=i)
                        for i in filtered[:25]
                    ]
                    select_item = Select(
                        placeholder="Select an item…",
                        options=opts,
                        min_values=1,
                        max_values=1,
                        custom_id="cat_item_select_v3",
                    )
                    select_item.callback = self.on_item
                    view2.add_item(select_item)
                back2 = Button(label="← Back", style=ButtonStyle.secondary)

                async def back_type(inter3: nextcord.Interaction):
                    await inter3.response.edit_message(embed=rpt, view=view)

                back2.callback = back_type
                view2.add_item(back2)
                await inter2.response.edit_message(embed=embed2, view=view2)

            select_type.callback = on_type
            view.add_item(select_type)

        report_btn = Button(
            label="⚠ Report File Error",
            style=ButtonStyle.danger,
        )

        async def on_report(inter2: nextcord.Interaction):
            await inter2.response.send_modal(
                FileErrorReportModal(
                    category,
                    item_rel_base,
                    inter2.message.jump_url,
                    inter2.user,
                )
            )

        report_btn.callback = on_report
        view.add_item(report_btn)

        back = Button(
            label="← Back to list",
            style=ButtonStyle.secondary,
            custom_id="back_to_list_v3",
        )

        async def on_back(inter2: nextcord.Interaction):
            embed2, view2 = self.build_item_list_view(category)
            await inter2.response.edit_message(embed=embed2, view=view2)

        back.callback = on_back
        view.add_item(back)
        if use_followup:
            await interaction.followup.send(embed=rpt, view=view, ephemeral=True)
        else:
            await interaction.response.edit_message(embed=rpt, view=view)


class RegistrationModal(Modal):
    def __init__(self, operator, member: nextcord.Member, session_key: str):
        super().__init__(title="Operator Registration")
        self.operator = operator
        self.member = member
        self.session_key = session_key
        self.password = TextInput(
            label="Set Password",
            style=TextInputStyle.short,
            min_length=6,
            max_length=32,
        )
        self.add_item(self.password)

    async def callback(self, interaction: nextcord.Interaction):
        level = detect_clearance(self.member)
        set_password(self.operator.user_id, self.password.value)
        set_clearance(self.operator.user_id, level)
        rank = detect_rank(self.member)
        desc = (
            "Operator Profile Generated:\n\n"
            f"ID: {self.operator.id_code}\n"
            f"Rank: {rank}\n"
            f"Clearance: Level-{level}\n"
            "Status: ACTIVE\n\n"
            "Your credentials are now stored in the Archive.\n"
            "Proceed to the Archive channel and log in via the terminal.\n\n"
            f"Session Key: {self.session_key}"
        )
        embed = Embed(title="[REGISTRATION COMPLETE]", description=desc, color=0x00FFCC)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class LoginModal(Modal):
    def __init__(self, operator, member: nextcord.Member):
        super().__init__(title="Operator Login")
        self.operator = operator
        self.member = member
        self.password = TextInput(
            label="Password",
            style=TextInputStyle.short,
            min_length=1,
            max_length=32,
        )
        self.add_item(self.password)

    async def callback(self, interaction: nextcord.Interaction):
        success, locked = verify_password(self.operator.user_id, self.password.value)
        if locked:
            await interaction.response.send_message(
                "⛔ Account locked. HICOM notified.", ephemeral=True
            )
            return
        if not success:
            await interaction.response.send_message("❌ Incorrect password.", ephemeral=True)
            return
        session_id = generate_session_id()
        cats = get_allowed_categories(self.operator.clearance, list_categories())
        view = View(timeout=None)
        view.add_item(CategorySelect(member=self.member, categories=cats))
        rank = detect_rank(self.member)
        desc = (
            f"Session ID: {session_id}\n\n"
            f"Welcome back, {rank} {self.operator.id_code}.\n"
            f"Clearance Level: {self.operator.clearance} (Secret)\n"
            "Surveillance Status: ACTIVE\n\n"
            "Select a directory to proceed:"
        )
        embed = Embed(
            title="[ARCHIVE TERMINAL ACCESS GRANTED]",
            description=desc,
            color=0x00FFCC,
        )
        embed.set_footer(text="Glacier Unit-7 Archive Terminal")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ResetPasswordModal(Modal):
    def __init__(self, operator):
        super().__init__(title="Reset Password")
        self.operator = operator
        self.password = TextInput(
            label="New Password",
            style=TextInputStyle.short,
            min_length=6,
            max_length=32,
        )
        self.add_item(self.password)

    async def callback(self, interaction: nextcord.Interaction):
        set_password(self.operator.user_id, self.password.value)
        await interaction.response.send_message("✅ Password reset.", ephemeral=True)


class IdChangeRequestModal(Modal):
    def __init__(self, current_id: str, user: nextcord.Member):
        super().__init__(title="Request ID Change")
        self.user = user
        self.current_id = current_id
        self.reason = TextInput(
            label=f"What would you like to be changed? (Current ID: {current_id})",
            style=TextInputStyle.short,
            max_length=100,
        )
        self.add_item(self.reason)

    async def callback(self, interaction: nextcord.Interaction):
        channel = interaction.client.get_channel(REPORT_REPLY_CHANNEL_ID)
        mention = (
            f"<@&{LEAD_ARCHIVIST_ROLE_ID}>" if LEAD_ARCHIVIST_ROLE_ID else "Lead Archivists"
        )
        content = (
            f"🆔 ID change request from {self.user.mention} (Current ID: `{self.current_id}`):\n"
            f"Requested ID: `{self.reason.value}`\n"
            f"{mention}"
        )
        view = IdChangeDecisionView(self.user, self.reason.value)
        if channel:
            try:
                await channel.send(content, view=view)
            except Exception:
                pass
        await interaction.response.send_message(
            "✅ ID change request submitted for review.", ephemeral=True
        )
        _last_id_change_request[self.user.id] = time.time()


class RootView(View):
    def __init__(self):
        super().__init__(timeout=None)
        login = Button(label="Enter Archive", style=ButtonStyle.primary, custom_id="login_root_v5")
        login.callback = self.handle_login
        self.add_item(login)

        bypass = Button(
            label="Clearance Bypass",
            style=ButtonStyle.secondary,
            custom_id="bypass_root_v1",
        )
        bypass.callback = self.handle_bypass
        self.add_item(bypass)

        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary, custom_id="refresh_root_v5")
        refresh.callback = self.refresh_menu
        self.add_item(refresh)

        archivist = Button(
            label="Archivist Menu",
            style=ButtonStyle.secondary,
            custom_id="archivist_root_v1",
        )
        archivist.callback = self.open_archivist_menu
        self.add_item(archivist)

        id_change = Button(
            label="REQUEST ID CHANGE",
            style=ButtonStyle.danger,
            custom_id="id_change_root_v1",
        )
        id_change.callback = self.handle_id_change_request
        self.add_item(id_change)

        forgot = Button(
            label="Forgot Password",
            style=ButtonStyle.secondary,
            custom_id="forgot_root_v1",
        )
        forgot.callback = self.handle_forgot
        self.add_item(forgot)

    async def handle_login(self, interaction: nextcord.Interaction):
        op = get_or_create_operator(interaction.user.id)
        if op.password_hash is None:
            await start_registration(interaction, op, interaction.user)
            return
        if has_active_session(op.user_id):
            touch_session(op.user_id)
            session_id = generate_session_id()
            cats = get_allowed_categories(op.clearance, list_categories())
            view = View(timeout=None)
            view.add_item(CategorySelect(member=interaction.user, categories=cats))
            desc = (
                f"Session ID: {session_id}\n\n"
                f"Operator Verified: {op.id_code}\n\n"
                f"> Clearance Level: {op.clearance} (Secret)\n"
                f"> Surveillance Status: ACTIVE\n\n"
                "Proceed by selecting a directory below:"
            )
            embed = Embed(title="[ARCHIVE TERMINAL ONLINE]", description=desc, color=0x00FFCC)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return
        try:
            await interaction.response.send_modal(LoginModal(op, interaction.user))
        except InteractionResponded:
            await interaction.followup.send_modal(LoginModal(op, interaction.user))

    async def handle_bypass(self, interaction: nextcord.Interaction):
        if not has_classified_clearance(interaction.user):
            return await interaction.response.send_message(
                "⛔ Classified clearance required.", ephemeral=True
            )

        session_id = generate_session_id()
        cats = list_categories()
        view = View(timeout=None)
        view.add_item(CategorySelect(member=interaction.user, categories=cats))
        desc = (
            f"Session ID: {session_id}\n\n"
            "Clearance bypass active.\n"
            "Surveillance Status: ACTIVE\n\n"
            "Proceed by selecting a directory below:"
        )
        embed = Embed(
            title="[ARCHIVE TERMINAL ACCESS GRANTED]",
            description=desc,
            color=0x00FFCC,
        )
        embed.set_footer(text="Glacier Unit-7 Archive Terminal")
        _bypass_sessions.add(interaction.user.id)
        asyncio.create_task(_clear_bypass(interaction.user.id))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def handle_id_change_request(self, interaction: nextcord.Interaction):
        now = time.time()
        last = _last_id_change_request.get(interaction.user.id, 0)
        if now - last < 24 * 3600:
            return await interaction.response.send_message(
                "⏳ You can only submit this request once every 24 hours.",
                ephemeral=True,
            )
        op = get_or_create_operator(interaction.user.id)
        try:
            await interaction.response.send_modal(
                IdChangeRequestModal(op.id_code, interaction.user)
            )
        except InteractionResponded:
            await interaction.followup.send_modal(
                IdChangeRequestModal(op.id_code, interaction.user)
            )

    async def handle_forgot(self, interaction: nextcord.Interaction):
        op = get_or_create_operator(interaction.user.id)
        try:
            await interaction.response.send_message(
                "Check your DMs to reset your password.", ephemeral=True
            )
        except InteractionResponded:
            await interaction.followup.send(
                "Check your DMs to reset your password.", ephemeral=True
            )
        try:
            view = View()
            btn = Button(
                label="Reset Password",
                style=ButtonStyle.primary,
                custom_id="reset_password_btn_v1",
            )

            async def on_press(inter: nextcord.Interaction):
                try:
                    await inter.response.send_modal(ResetPasswordModal(op))
                except InteractionResponded:
                    await inter.followup.send_modal(ResetPasswordModal(op))

            btn.callback = on_press
            view.add_item(btn)
            await interaction.user.send(
                "Use the button below to set a new password.", view=view
            )
        except Exception:
            await interaction.followup.send(
                "Unable to send you a DM. Please enable direct messages.",
                ephemeral=True,
            )

    async def open_archivist_menu(self, interaction: nextcord.Interaction):
        import main

        await main.archivist_cmd(interaction)

    async def refresh_menu(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=RootView(),
        )
