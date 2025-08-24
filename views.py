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
)

# ===== RP System Alerts =====
ALERT_MESSAGES = [
    "Archive Node Delta not responding – rerouting traffic…",
    "Quantum indexer misaligned – initiating recalibration…",
    "Remote vault link degraded – seeking alternative route…",
]

# Cache of last successful access sequence per user
_last_verified: Dict[int, float] = {}


async def maybe_system_alert(
    interaction: nextcord.Interaction, on_fix=None
) -> bool:
    """Randomly display a fatal system error before continuing."""
    if random.random() < 0.12:
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
        if await maybe_system_alert(interaction):
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
            f"✅ {interaction.user.mention} granted {self.requester} access to"
            f" `{self.category}/{self.item}`."
        )
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    async def deny(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        if await maybe_system_alert(interaction):
            return
        import main

        msg = (
            f"❌ {self.requester.mention} your request for "
            f"`{self.category}/{self.item}` was denied by {interaction.user.mention}."
        )
        await interaction.response.send_message(msg)
        await main.log_action(
            f"❌ {interaction.user.mention} denied {self.requester} access to"
            f" `{self.category}/{self.item}`."
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
        if await maybe_system_alert(interaction):
            return
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
        await main.log_action(
            f"✉️ {self.user.mention} requested clearance for `{self.category}/{self.item}`."
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
            max_length=4000,
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
            f"⚠️ {interaction.user.mention} reported error '{error_type}' on `{file_path}`: {description}"
        )


class CategorySelect(Select):
    def __init__(self):
        cats = list_categories()
        super().__init__(
            placeholder="Select a category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in cats[:25]],
            min_values=1, max_values=1,
            custom_id="cat_select_v3"
        )
        self.category = None

    def build_item_list_view(self, category: str):
        items = list_items_recursive(category)
        embed = Embed(
            title=f"Archive: {category.replace('_',' ').title()}",
            description=("Select an item…" if items else "_No files in this category._"),
            color=0x00FFCC
        )
        view = View(timeout=None)
        if items:
            select_item = Select(
                placeholder="Select an item…",
                options=[SelectOption(label=i, value=i) for i in items[:25]],
                min_values=1, max_values=1,
                custom_id="cat_item_select_v3",
            )
            select_item.callback = self.on_item
            view.add_item(select_item)
        return embed, view

    async def callback(self, interaction: nextcord.Interaction):
        if await maybe_system_alert(interaction):
            return
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
                f"🚫 {interaction.user.mention} attempted to access `{category}/{item_rel_base}{ext}` without clearance."
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
                        f"Unauthorized access attempt by {interaction.user.mention} on `{category}/{item_rel_base}{ext}`. Case {case_ref}"
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
                f"🚫 {interaction.user.mention} attempted to access `{category}/{item_rel_base}{ext}` without clearance."
            )
            view = ClearanceRequestView(interaction.user, category, item_rel_base)
            sender = (
                interaction.followup.send if use_followup else interaction.response.send_message
            )
            return await sender(
                "⛔ Insufficient clearance.", ephemeral=True, view=view
            )

        import main
        await main.log_action(f"📄 {interaction.user.mention} accessed `{category}/{item_rel_base}{ext}`.")

        rpt = Embed(
            title=f"{item_rel_base.split('/')[-1].replace('_',' ').title()} — {category.title()}",
            color=0x00FFCC
        )
        roles_needed = [f"<@&{str(r)}>" for r in required] if required else ["None (public)"]
        rpt.add_field(name="🔐 Required Clearance", value=", ".join(roles_needed), inline=False)

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
                        rpt.add_field(name=k.replace("_"," ").title(), value=str(v), inline=False)
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
            show = blob if len(blob) <= 1800 else blob[:1800] + "\n…(truncated)"
            if re.search(r"https?://", show):
                rpt.add_field(name="Contents", value=show, inline=False)
            else:
                rpt.add_field(name="Contents", value=f"```txt\n{show}\n```", inline=False)

        notes = list_file_annotations(category, item_rel_base)
        if notes:
            summary = "\n".join(notes)
            if len(summary) > 1024:
                summary = summary[-1024:]
            rpt.add_field(name="🖊️ Archivist Notes", value=summary, inline=False)

        items = list_items_recursive(category)
        view = View(timeout=None)

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


class RootView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelect())
        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary, custom_id="refresh_root_v3")
        refresh.callback = self.refresh_menu
        self.add_item(refresh)

    async def refresh_menu(self, interaction: nextcord.Interaction):
        if await maybe_system_alert(interaction):
            return
        await interaction.response.edit_message(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=RootView(),
        )
