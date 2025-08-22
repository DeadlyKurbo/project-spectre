import io
import random

import nextcord
from nextcord import Embed, SelectOption, ButtonStyle
from nextcord.ui import View, Select, Button

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
)

# ===== RP System Alerts =====
ALERT_MESSAGES = [
    "Archive Node Delta not responding – rerouting traffic…",
    "Quantum indexer misaligned – initiating recalibration…",
    "Remote vault link degraded – seeking alternative route…",
]


class SystemAlertView(View):
    """Offer a button to resolve RP system alerts."""

    def __init__(self, on_fix=None):
        super().__init__(timeout=30)
        self.on_fix = on_fix
        btn = Button(label="Run Diagnostics", style=ButtonStyle.danger)
        btn.callback = self.fix
        self.add_item(btn)

    async def fix(self, interaction: nextcord.Interaction):
        import main

        await interaction.response.send_message(
            "🛠️ Diagnostics complete. Systems nominal.", ephemeral=True
        )
        await main.log_action(
            f"🛠️ {interaction.user} ran diagnostics after a system alert."
        )
        if self.on_fix:
            await self.on_fix(interaction)
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)


async def maybe_system_alert(
    interaction: nextcord.Interaction, on_fix=None
) -> bool:
    """Randomly display a critical system alert and halt normal handling."""
    if random.random() < 0.03:
        view = SystemAlertView(on_fix=on_fix)
        await interaction.response.send_message(
            embed=Embed(
                title="⚠️ Critical System Alert",
                description=random.choice(ALERT_MESSAGES),
                color=0xFF0000,
            ),
            view=view,
            ephemeral=True,
        )
        return True
    return False


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
            f"✅ {interaction.user} granted {self.requester} access to"
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
            f"❌ {interaction.user} denied {self.requester} access to"
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
            f"✉️ {self.user} requested clearance for `{self.category}/{self.item}`."
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
            await self._show_item(inter, item_rel_base, use_followup=True)

        if await maybe_system_alert(interaction, on_fix=resume):
            return
        await self._show_item(interaction, item_rel_base)

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
                f"🚫 {interaction.user} attempted to access `{category}/{item_rel_base}{ext}` without clearance."
            )
            view = ClearanceRequestView(interaction.user, category, item_rel_base)
            sender = (
                interaction.followup.send if use_followup else interaction.response.send_message
            )
            return await sender(
                "⛔ Insufficient clearance.", ephemeral=True, view=view
            )

        import main
        await main.log_action(f"📄 {interaction.user} accessed `{category}/{item_rel_base}{ext}`.")

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
            rpt.add_field(name="Contents", value=f"```txt\n{show}\n```", inline=False)

        items = list_items_recursive(category)
        select_another = Select(
            placeholder="Select another item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1,
            custom_id="cat_item_select_again_v3",
        )
        select_another.callback = self.on_item

        back = Button(label="← Back to list", style=ButtonStyle.secondary, custom_id="back_to_list_v3")

        async def on_back(inter2: nextcord.Interaction):
            embed2, view2 = self.build_item_list_view(category)
            await inter2.response.edit_message(embed=embed2, view=view2)

        back.callback = on_back

        view = View(timeout=None)
        view.add_item(select_another)
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
