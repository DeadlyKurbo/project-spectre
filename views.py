import io
import random
import asyncio
import re
import time
from typing import Dict

import nextcord
from nextcord import (
    Embed,
    SelectOption,
    ButtonStyle,
    InteractionResponded,
    TextInputStyle,
    PartialEmoji,
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
    CONTENT_MAX_LENGTH,
    PAGE_SEPARATOR,
    CATEGORY_STYLES,
    ARCHIVE_EMOJI,
    ARCHIVE_COLOR,
)
from server_config import get_server_config, invalidate_config
from utils import get_category_label, iter_category_styles

from operator_login import (
    get_or_create_operator,
    generate_session_id,
    update_id_code,
)
from registration import start_registration, ResetPasswordModal

# Mapping of embed colors to Nextcord button styles so category buttons can
# roughly match their associated hues.
_COLOR_STYLE_MAP = {
    0xFF0000: ButtonStyle.danger,   # red
    0x00FF00: ButtonStyle.success,  # green
    0x0000FF: ButtonStyle.primary,  # blue
    0xFFFF00: ButtonStyle.primary,  # yellow -> blue style as closest
    0xFFA500: ButtonStyle.danger,   # orange -> red style
    0xFFFFFF: ButtonStyle.secondary,  # white/neutral
    0x800080: ButtonStyle.secondary,  # purple -> neutral
}


def category_label(slug: str, guild_id: int | None = None) -> str:
    """Return display label for ``slug`` reflecting runtime changes."""
    return get_category_label(slug, guild_id)


def _guild_id_from_interaction(interaction: nextcord.Interaction) -> int | None:
    """Best-effort extraction of a guild ID from ``interaction``.

    Test stubs may only provide ``guild`` without ``guild_id`` so we
    gracefully handle both attributes.
    """
    gid = getattr(interaction, "guild_id", None)
    if gid is None:
        guild_obj = getattr(interaction, "guild", None)
        if guild_obj is not None:
            gid = getattr(guild_obj, "id", None)
    return gid


def _color_to_style(color: int) -> ButtonStyle:
    """Return a :class:`ButtonStyle` approximating ``color``.

    Discord buttons only support a handful of preset styles so we map the
    requested RGB ``color`` to the nearest available style.  A small lookup
    table handles exact matches for a few common colours, otherwise the
    function computes the Euclidean distance between the requested colour and
    the canonical colour for each style and returns the closest one.  This
    ensures category buttons inherit a reasonable hue even when arbitrary
    colours are configured in :data:`constants.CATEGORY_STYLES`.
    """

    if color in _COLOR_STYLE_MAP:
        return _COLOR_STYLE_MAP[color]

    # Base colours for the standard Discord styles taken from the official
    # branding palette.
    base = {
        ButtonStyle.primary: (0x58, 0x65, 0xF2),   # blurple
        ButtonStyle.success: (0x57, 0xF2, 0x87),   # green
        ButtonStyle.danger: (0xED, 0x42, 0x45),    # red
        ButtonStyle.secondary: (0x4F, 0x54, 0x5C), # grey
    }

    r, g, b = (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF

    def _dist(rgb):
        return (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2

    style = min(base.items(), key=lambda item: _dist(item[1]))[0]
    return style

# ===== RP System Alerts =====
ALERT_MESSAGES = [
    "Archive Node Delta not responding – rerouting traffic…",
    "Quantum indexer misaligned – initiating recalibration…",
    "Remote vault link degraded – seeking alternative route…",
]

# Cache of last successful access sequence per user
_last_verified: Dict[int, float] = {}


def _user_mention(interaction: nextcord.Interaction) -> str:
    """Return a display name for logging."""
    return interaction.user.mention


async def maybe_system_alert(
    interaction: nextcord.Interaction, on_fix=None
) -> bool:
    """Randomly display a fatal system error before continuing."""
    if random.random() < 0.02:
        embed = Embed(
            title=" Fatal System Error",
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
        " Establishing secure uplink to Glacier Unit-7 Mainframe…\n"
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
        gid = _guild_id_from_interaction(interaction)
        cfg = get_server_config(gid or 0)
        role_id = cfg.get("LEAD_ARCHIVIST_ROLE_ID")
        if role_id and role_id not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message(
                " Lead Archivist only.", ephemeral=True
            )
            return False
        return True

    async def grant(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        import main

        grant_temp_clearance(self.category, self.item, self.requester.id)
        msg = (
            f" {self.requester.mention} your request for "
            f"`{self.category}/{self.item}` was approved by {interaction.user.mention}. "
            "You have 10 minutes to access the file."
        )
        await interaction.response.send_message(msg)
        await main.log_action(
            f" {_user_mention(interaction)} granted {self.requester.mention} access to `{self.category}/{self.item}`."
        )
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    async def deny(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        import main

        msg = (
            f" {self.requester.mention} your request for "
            f"`{self.category}/{self.item}` was denied by {interaction.user.mention}."
        )
        await interaction.response.send_message(msg)
        await main.log_action(
            f" {_user_mention(interaction)} denied {self.requester.mention} access to `{self.category}/{self.item}`."
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
        gid = _guild_id_from_interaction(interaction)
        cfg = get_server_config(gid or 0)
        role_id = cfg.get("LEAD_ARCHIVIST_ROLE_ID")
        if role_id and role_id not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message(
                " Lead Archivist only.", ephemeral=True
            )
            return False
        return True

    async def approve(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        import main

        update_id_code(self.requester.id, self.new_id)
        msg = (
            f" {self.requester.mention}'s ID updated to `{self.new_id}` by {interaction.user.mention}."
        )
        await interaction.response.send_message(msg)
        await main.log_action(
            f" {_user_mention(interaction)} approved ID change for {self.requester.mention} to `{self.new_id}`."
        )
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    async def deny(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        import main

        msg = (
            f" {self.requester.mention}'s ID change request was denied by {interaction.user.mention}."
        )
        await interaction.response.send_message(msg)
        await main.log_action(
            f" {_user_mention(interaction)} denied ID change for {self.requester.mention} requesting `{self.new_id}`."
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

        gid = _guild_id_from_interaction(interaction)
        cfg = get_server_config(gid or 0)
        channel_id = cfg.get("CLEARANCE_REQUESTS_CHANNEL_ID")
        channel = None
        if channel_id:
            channel = interaction.guild.get_channel(channel_id)
            if not channel:
                try:
                    channel = await interaction.client.fetch_channel(channel_id)
                except Exception:
                    channel = None

        role_id = cfg.get("LEAD_ARCHIVIST_ROLE_ID")
        mention = f"<@&{role_id}>" if role_id else "Lead Archivists"

        file = None
        try:
            found = _find_existing_item_key("personnel", str(self.user.id), guild_id=gid)
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
            " Clearance request sent.", ephemeral=True
        )
        await main.log_action(
            f" {self.user.mention} requested clearance for `{self.category}/{self.item}`."
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
        gid = _guild_id_from_interaction(interaction)
        cfg = get_server_config(gid or 0)
        channel_id = cfg.get("LEAD_NOTIFICATION_CHANNEL_ID")
        channel = None
        if channel_id:
            channel = interaction.guild.get_channel(channel_id)
            if not channel:
                try:
                    channel = await interaction.client.fetch_channel(channel_id)
                except Exception:
                    channel = None
        error_type = self.error_type.value.strip() or "Unspecified"
        description = self.details.value.strip()
        contact = self.contact.value.strip() if self.contact.value else str(interaction.user)
        from datetime import datetime, UTC

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        file_path = f"{self.category}/{self.item}"
        msg = (
            " File Error Report\n"
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
            f" {_user_mention(interaction)} reported error '{error_type}' on `{file_path}`: {description}"
        )


class CategorySelect(Select):
    def __init__(
        self,
        member: nextcord.Member | None = None,
        categories: list[str] | None = None,
    ):
        self.member = member
        self.guild_id = getattr(getattr(member, "guild", None), "id", None)
        self.config = get_server_config(self.guild_id) if self.guild_id else None
        self.category = None
        self._cache: dict[str, list[str]] = {}

        cats = categories or list_categories(guild_id=self.guild_id)
        options: list[SelectOption] = []
        for slug, label, emoji, _color in iter_category_styles(cats, guild_id=self.guild_id):
            # Lazily populate the item cache when a category is actually opened
            # rather than preloading all dossier listings up front.  In
            # production the archive can contain thousands of files spread
            # across many categories.  Creating a select for a single operator
            # previously loaded every file name into ``self._cache`` which
            # multiplied memory usage for each active session and eventually
            # exhausted the bot's RAM.  By deferring the expensive lookups we
            # keep the view lightweight and only store item lists for categories
            # the user interacts with.
            options.append(SelectOption(label=label, value=slug, emoji=emoji))
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

        try:
            return list_items_recursive(category, guild_id=self.guild_id)
        except TypeError:
            return list_items_recursive(category)

    def build_item_list_view(self, category: str):
        items = self._cache.get(category)
        if items is None:
            items = self._filter_items(category)
            self._cache[category] = items
        styles = (self.config.get("CATEGORY_STYLES", CATEGORY_STYLES) if self.config else CATEGORY_STYLES)
        base_color = (self.config.get("ARCHIVE_COLOR", ARCHIVE_COLOR) if self.config else ARCHIVE_COLOR)
        emoji, color = styles.get(category, (None, base_color))
        title = category_label(category, self.guild_id)
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
        category = self.category or list_categories(guild_id=self.guild_id)[0]
        found = _find_existing_item_key(category, item_rel_base, guild_id=self.guild_id)
        if not found:
            sender = interaction.followup.send if use_followup else interaction.response.send_message
            await sender(" File not found.", ephemeral=True)
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
                f" {_user_mention(interaction)} attempted to access `{category}/{item_rel_base}{ext}` without clearance."
            )
            gid = _guild_id_from_interaction(interaction)
            cfg = get_server_config(gid or 0)
            channel_id = cfg.get("SECURITY_LOG_CHANNEL_ID")
            channel = interaction.guild.get_channel(channel_id) if channel_id else None
            if channel_id and not channel:
                try:
                    channel = await interaction.client.fetch_channel(channel_id)
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
        category = self.category or list_categories(guild_id=self.guild_id)[0]

        found = _find_existing_item_key(category, item_rel_base, guild_id=self.guild_id)
        if not found:
            return await interaction.response.send_message(" File not found.", ephemeral=True)
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
                f" {_user_mention(interaction)} attempted to access `{category}/{item_rel_base}{ext}` without clearance."
            )
            view = ClearanceRequestView(interaction.user, category, item_rel_base)
            sender = (
                interaction.followup.send if use_followup else interaction.response.send_message
            )
            return await sender(
                " Insufficient clearance.", ephemeral=True, view=view
            )

        import main
        await main.log_action(
            f" {_user_mention(interaction)} accessed `{category}/{item_rel_base}{ext}`."
        )

        gid = _guild_id_from_interaction(interaction)
        cfg = get_server_config(gid or 0)
        styles = cfg.get("CATEGORY_STYLES", CATEGORY_STYLES)
        base_color = cfg.get("ARCHIVE_COLOR", ARCHIVE_COLOR)
        emoji, color = styles.get(category, (None, base_color))
        item_title = item_rel_base.split('/')[-1].replace('_', ' ').title()
        cat_title = category_label(category, gid)
        title = f"{item_title} — {cat_title}"
        if emoji:
            title = f"{emoji} {title}"
        rpt = Embed(title=title, color=color)
        roles_needed = [f"<@&{str(r)}>" for r in required] if required else ["None (public)"]
        rpt.add_field(name=" Required Clearance", value=", ".join(roles_needed), inline=False)

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
                        rpt.add_field(name=" Attached File", value=f"[Open]({v})", inline=False)
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
                return await sender(" Could not read file.", ephemeral=True)
            if PAGE_SEPARATOR in blob:
                pages = blob.split(PAGE_SEPARATOR)
            else:
                pages = [blob[i : i + 1000] for i in range(0, len(blob), 1000)]

            image_re = re.compile(r"^\[IMAGE\]:\s*(https?://\S+)$", re.IGNORECASE)
            page_images: list[list[str]] = []
            for i, pg in enumerate(pages):
                lines = pg.splitlines()
                imgs: list[str] = []
                while lines and image_re.match(lines[-1]):
                    m = image_re.match(lines[-1])
                    assert m is not None
                    imgs.append(m.group(1))
                    lines.pop()
                pages[i] = "\n".join(lines)
                page_images.append(list(reversed(imgs)))

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
            if page_images[page_index]:
                rpt.set_thumbnail(url=page_images[page_index][0])
                rpt.set_image(url=page_images[page_index][-1])

        notes = list_file_annotations(category, item_rel_base)
        if notes:
            summary = "\n".join(notes)
            if len(summary) > 1024:
                summary = summary[-1024:]
            rpt.add_field(name=" Archivist Notes", value=summary, inline=False)

        items = list_items_recursive(category, guild_id=self.guild_id)
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
                if page_images[page_index]:
                    rpt.set_thumbnail(url=page_images[page_index][0])
                    rpt.set_image(url=page_images[page_index][-1])
                else:
                    rpt.set_thumbnail(url=None)
                    rpt.set_image(url=None)
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
                    color=base_color,
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
            label=" Report File Error",
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


class CategoryButton(Button):
    def __init__(self, category: str, member: nextcord.Member | None = None):
        self.category = category
        self.member = member
        self.guild_id = getattr(getattr(member, "guild", None), "id", None)
        cfg = get_server_config(self.guild_id) if self.guild_id else None
        self.config = cfg
        styles = cfg.get("CATEGORY_STYLES", CATEGORY_STYLES) if cfg else CATEGORY_STYLES
        base_color = cfg.get("ARCHIVE_COLOR", ARCHIVE_COLOR) if cfg else ARCHIVE_COLOR
        emoji, color = styles.get(category, (None, base_color))
        label = category_label(category, self.guild_id)
        kwargs = {
            "label": label,
            "style": _color_to_style(color),
            "custom_id": f"cat_btn_{category}",
        }

        if isinstance(emoji, str):
            emoji = emoji.strip() or None

        if emoji:
            try:
                kwargs["emoji"] = emoji
                super().__init__(**kwargs)
            except Exception:
                # If Discord rejects the emoji (e.g. invalid unicode), fall back to
                # embedding it directly in the label so the button still displays a
                # visual marker rather than failing entirely.
                kwargs.pop("emoji", None)
                kwargs["label"] = f"{emoji} {label}"
                super().__init__(**kwargs)
        else:
            super().__init__(**kwargs)

    def _filter_items(self) -> list[str]:
        try:
            return list_items_recursive(self.category, guild_id=self.guild_id)
        except TypeError:
            return list_items_recursive(self.category)

    def build_item_list_view(self):
        items = self._filter_items()
        styles = self.config.get("CATEGORY_STYLES", CATEGORY_STYLES) if self.config else CATEGORY_STYLES
        base_color = self.config.get("ARCHIVE_COLOR", ARCHIVE_COLOR) if self.config else ARCHIVE_COLOR
        emoji, color = styles.get(self.category, (None, base_color))
        title = category_label(self.category, self.guild_id)
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
        embed, view = self.build_item_list_view()
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
        category = self.category or list_categories(guild_id=self.guild_id)[0]
        found = _find_existing_item_key(category, item_rel_base, guild_id=self.guild_id)
        if not found:
            sender = interaction.followup.send if use_followup else interaction.response.send_message
            await sender(" File not found.", ephemeral=True)
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
                f" {_user_mention(interaction)} attempted to access `{category}/{item_rel_base}{ext}` without clearance."
            )
            gid = _guild_id_from_interaction(interaction)
            cfg = get_server_config(gid or 0)
            channel_id = cfg.get("SECURITY_LOG_CHANNEL_ID")
            channel = interaction.guild.get_channel(channel_id) if channel_id else None
            if channel_id and not channel:
                try:
                    channel = await interaction.client.fetch_channel(channel_id)
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
        category = self.category or list_categories(guild_id=self.guild_id)[0]

        found = _find_existing_item_key(category, item_rel_base, guild_id=self.guild_id)
        if not found:
            return await interaction.response.send_message(" File not found.", ephemeral=True)
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
                f" {_user_mention(interaction)} attempted to access `{category}/{item_rel_base}{ext}` without clearance."
            )
            view = ClearanceRequestView(interaction.user, category, item_rel_base)
            sender = (
                interaction.followup.send if use_followup else interaction.response.send_message
            )
            return await sender(
                " Insufficient clearance.", ephemeral=True, view=view
            )

        import main
        await main.log_action(
            f" {_user_mention(interaction)} accessed `{category}/{item_rel_base}{ext}`."
        )

        gid = _guild_id_from_interaction(interaction)
        cfg = get_server_config(gid or 0)
        styles = cfg.get("CATEGORY_STYLES", CATEGORY_STYLES)
        base_color = cfg.get("ARCHIVE_COLOR", ARCHIVE_COLOR)
        emoji, color = styles.get(category, (None, base_color))
        item_title = item_rel_base.split('/')[-1].replace('_', ' ').title()
        cat_title = category_label(category, gid)
        title = f"{item_title} — {cat_title}"
        if emoji:
            title = f"{emoji} {title}"
        rpt = Embed(title=title, color=color)
        roles_needed = [f"<@&{str(r)}>" for r in required] if required else ["None (public)"]
        rpt.add_field(name=" Required Clearance", value=", ".join(roles_needed), inline=False)

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
                        rpt.add_field(name=" Attached File", value=f"[Open]({v})", inline=False)
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
                return await sender(" Could not read file.", ephemeral=True)
            if PAGE_SEPARATOR in blob:
                pages = blob.split(PAGE_SEPARATOR)
            else:
                pages = [blob[i : i + 1000] for i in range(0, len(blob), 1000)]

            image_re = re.compile(r"^\[IMAGE\]:\s*(https?://\S+)$", re.IGNORECASE)
            page_images: list[list[str]] = []
            for i, pg in enumerate(pages):
                lines = pg.splitlines()
                imgs: list[str] = []
                while lines and image_re.match(lines[-1]):
                    m = image_re.match(lines[-1])
                    assert m is not None
                    imgs.append(m.group(1))
                    lines.pop()
                pages[i] = "\n".join(lines)
                page_images.append(list(reversed(imgs)))

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
            if page_images[page_index]:
                rpt.set_image(url=page_images[page_index][-1])

        notes = list_file_annotations(category, item_rel_base)
        if notes:
            summary = "\n".join(notes)
            if len(summary) > 1024:
                summary = summary[-1024:]
            rpt.add_field(name=" Archivist Notes", value=summary, inline=False)

        items = list_items_recursive(category, guild_id=self.guild_id)
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
                if page_images[page_index]:
                    rpt.set_image(url=page_images[page_index][-1])
                else:
                    rpt.set_image(url=None)
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
                    color=base_color,
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
            label=" Report File Error",
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
            embed2, view2 = self.build_item_list_view()
            await inter2.response.edit_message(embed=embed2, view=view2)

        back.callback = on_back
        view.add_item(back)
        if use_followup:
            await interaction.followup.send(embed=rpt, view=view, ephemeral=True)
        else:
            await interaction.response.edit_message(embed=rpt, view=view)


class CategoryMenu(View):
    """Interactive dossier category selector with pagination support."""

    _MAX_OPTIONS = 25

    def __init__(
        self,
        member: nextcord.Member | None = None,
        categories: list[str] | None = None,
    ):
        super().__init__(timeout=None)
        self.member = member
        self.guild_id = getattr(getattr(member, "guild", None), "id", None)
        self.config = get_server_config(self.guild_id) if self.guild_id else None
        self._pages: list[list[SelectOption]] = []
        self._page_index = 0
        self._prev_button: Button | None = None
        self._next_button: Button | None = None

        cats = categories or list_categories(guild_id=self.guild_id)
        # Deduplicate while preserving order to avoid duplicate select values
        seen: set[str] = set()
        cats = [c for c in cats if not (c in seen or seen.add(c))]
        options: list[SelectOption] = []
        styles = (
            self.config.get("CATEGORY_STYLES", CATEGORY_STYLES)
            if self.config
            else CATEGORY_STYLES
        )
        base_color = (
            self.config.get("ARCHIVE_COLOR", ARCHIVE_COLOR)
            if self.config
            else ARCHIVE_COLOR
        )
        for c in cats:
            try:
                items = list_items_recursive(c, guild_id=self.guild_id)
            except TypeError:
                items = list_items_recursive(c)
            emoji, _color = styles.get(c, (None, base_color))
            label = category_label(c, self.guild_id)
            options.append(
                SelectOption(
                    label=label,
                    value=c,
                    emoji=emoji,
                    description=f"{len(items)} file(s)",
                )
            )

        if not options:
            select = Select(
                placeholder="No categories available",
                options=[
                    SelectOption(
                        label="No categories available",
                        value="__none__",
                        description="Archive is empty",
                    )
                ],
                min_values=1,
                max_values=1,
                custom_id="cat_menu_select_v1",
            )
            select.disabled = True
            self.select = select
            self.add_item(select)
            return

        self._pages = [
            options[i : i + self._MAX_OPTIONS]
            for i in range(0, len(options), self._MAX_OPTIONS)
        ]
        self.select = Select(
            placeholder=self._placeholder(),
            options=list(self._pages[self._page_index]),
            min_values=1,
            max_values=1,
            custom_id="cat_menu_select_v1",
        )

        async def on_select(interaction: nextcord.Interaction):
            cat = interaction.data["values"][0]
            btn = CategoryButton(cat, member=member)
            await btn.callback(interaction)

        self.select.callback = on_select
        self.add_item(self.select)

        if len(self._pages) > 1:
            self._prev_button = Button(
                label="◀ Prev",
                style=ButtonStyle.secondary,
                custom_id="cat_menu_prev_v1",
            )
            self._next_button = Button(
                label="Next ▶",
                style=ButtonStyle.secondary,
                custom_id="cat_menu_next_v1",
            )

            async def go_prev(interaction: nextcord.Interaction):
                await self._change_page(-1, interaction)

            async def go_next(interaction: nextcord.Interaction):
                await self._change_page(1, interaction)

            self._prev_button.callback = go_prev
            self._next_button.callback = go_next
            self._update_nav_buttons()
            self.add_item(self._prev_button)
            self.add_item(self._next_button)

    def _placeholder(self) -> str:
        if len(self._pages) <= 1:
            return "Select a category…"
        return f"Select a category… (Page {self._page_index + 1}/{len(self._pages)})"

    def _update_nav_buttons(self) -> None:
        if not self._pages:
            return
        if self._prev_button is not None:
            self._prev_button.disabled = self._page_index == 0
        if self._next_button is not None:
            self._next_button.disabled = self._page_index >= len(self._pages) - 1

    def _update_page_state(self) -> None:
        self.select.options = list(self._pages[self._page_index])
        self.select.placeholder = self._placeholder()
        self._update_nav_buttons()

    async def _change_page(
        self, delta: int, interaction: nextcord.Interaction
    ) -> None:
        new_index = min(
            max(self._page_index + delta, 0),
            len(self._pages) - 1,
        )
        if new_index == self._page_index:
            await interaction.response.edit_message(view=self)
            return
        self._page_index = new_index
        self._update_page_state()
        await interaction.response.edit_message(view=self)


class RootView(View):
    def __init__(self, guild_id: int | None = None):
        self.guild_id = guild_id
        try:
            asyncio.get_running_loop()
            super().__init__(timeout=None)
            self._setup_buttons()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_init())

    async def _async_init(self):
        super().__init__(timeout=None)
        self._setup_buttons()

    def _setup_buttons(self):
        cfg = get_server_config(self.guild_id or 0)
        buttons = cfg.get("ROOT_BUTTONS", {})

        def make_button(key: str, default_label: str, default_style: ButtonStyle, custom_id: str | None):
            info = buttons.get(key, {})
            label = info.get("label", default_label)
            style_name = info.get("style")
            if style_name:
                style = getattr(ButtonStyle, style_name.lower(), default_style)
            else:
                style = default_style
            btn = Button(label=label, style=style, custom_id=custom_id)
            return btn

        enter = make_button("enter", "Enter Archive", ButtonStyle.primary, "enter_archive_root")
        enter.callback = self.open_archive
        self.add_item(enter)

        refresh = make_button("refresh", " Refresh", ButtonStyle.primary, "refresh_root")
        refresh.callback = self.refresh_menu
        self.add_item(refresh)

        archivist = make_button("archivist", "Archivist Menu", ButtonStyle.secondary, "archivist_root")
        archivist.callback = self.open_archivist_menu
        self.add_item(archivist)

        help_btn = make_button("help", "Help", ButtonStyle.danger, None)
        help_btn.callback = self.open_help
        self.add_item(help_btn)

    async def open_archive(self, interaction: nextcord.Interaction):
        from archivist import is_archive_locked, _is_high_command

        if is_archive_locked() and not _is_high_command(interaction.user):
            return await interaction.response.send_message(
                " Archive access locked.", ephemeral=True
            )

        session_id = generate_session_id()
        gid = _guild_id_from_interaction(interaction)
        cats = list_categories(guild_id=gid)
        view = CategoryMenu(member=interaction.user, categories=cats)
        desc = (
            f"Session ID: {session_id}\n\n"
            "Proceed by selecting a directory below:"
        )
        cfg = get_server_config(gid or 0)
        styles = cfg.get("CATEGORY_STYLES", {})
        archive_emoji, archive_color = styles.get(
            "archive", (ARCHIVE_EMOJI, cfg.get("ARCHIVE_COLOR", ARCHIVE_COLOR))
        )
        embed = Embed(
            title=f"{archive_emoji} [ARCHIVE TERMINAL ACCESS GRANTED]",
            description=desc,
            color=archive_color,
        )
        footer = cfg.get("ROOT_FOOTER")
        if footer:
            embed.set_footer(text=footer)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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

    async def open_help(self, interaction: nextcord.Interaction):
        from archivist import ReportProblemModal

        await interaction.response.send_modal(ReportProblemModal(interaction.user))

    async def open_archivist_menu(self, interaction: nextcord.Interaction):
        import main

        await main.archivist_cmd(interaction)

    async def refresh_menu(self, interaction: nextcord.Interaction):
        gid = _guild_id_from_interaction(interaction)
        invalidate_config(gid)
        cfg = get_server_config(gid or 0)
        color = cfg.get("ARCHIVE_COLOR", ARCHIVE_COLOR)
        title = cfg.get("INTRO_TITLE", INTRO_TITLE)
        desc = cfg.get("INTRO_DESC", INTRO_DESC)
        embed = Embed(title=title, description=desc, color=color)
        footer = cfg.get("ROOT_FOOTER")
        if footer:
            embed.set_footer(text=footer)
        thumb = cfg.get("ROOT_THUMBNAIL")
        if thumb:
            embed.set_thumbnail(url=thumb)
        await interaction.response.edit_message(
            embed=embed,
            view=RootView(guild_id=gid),
        )
