import nextcord
from nextcord import Embed, SelectOption, ButtonStyle
from nextcord.ui import View, Select, Button

# Altijd via utils.*
from utils.file_ops import (
    list_categories, list_items_recursive, _find_existing_item_key,
    get_required_roles, has_access
)
from storage_spaces import read_json, read_text

class CategorySelect(Select):
    def __init__(self, bot: nextcord.Client | None = None):
        self.bot = bot
        cats = list_categories()
        super().__init__(
            placeholder="Select a category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in cats[:25]],
            min_values=1, max_values=1,
            custom_id="cat_select_v5"
        )
        self.category = None

    def build_item_list_view(self, category: str, user: nextcord.Member | None = None):
        items = list_items_recursive(category)
        if user is not None:
            roles = {r.id for r in user.roles}
            owner_admin = (user.id == user.guild.owner_id or user.guild_permissions.administrator)
            items = [i for i in items if has_access(category, i, roles, owner_admin)[0]]

        embed = Embed(
            title=f"Archive: {category.replace('_',' ').title()}",
            description=("Select an item…" if items else "_No files in this category._"),
            color=0x00FFCC
        )
        view = View(timeout=None)
        view.bot = self.bot
        if items:
            select_item = Select(
                placeholder="Select an item…",
                options=[SelectOption(label=i, value=i) for i in items[:25]],
                min_values=1, max_values=1,
                custom_id="cat_item_select_v5"
            )
            select_item.callback = self.on_item
            view.add_item(select_item)
        return embed, view

    async def callback(self, interaction: nextcord.Interaction):
        self.category = self.values[0]
        embed, view = self.build_item_list_view(self.category, interaction.user)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def show_item(self, interaction: nextcord.Interaction, category: str, item_rel_base: str):
        found = _find_existing_item_key(category, item_rel_base)
        if not found:
            return await interaction.response.send_message("❌ File not found.", ephemeral=True)
        key, ext = found

        user_roles = {r.id for r in interaction.user.roles}
        owner_admin = (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator)
        allowed, required = has_access(category, item_rel_base, user_roles, owner_admin)
        if not allowed:
            import main
            await main.log_action(f"🚫 {interaction.user} attempted to access `{category}/{item_rel_base}{ext}` without clearance.")
            return await interaction.response.send_message("⛔ Insufficient clearance.", ephemeral=True)

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
                return await interaction.response.send_message("❌ Could not read file.", ephemeral=True)
            show = blob if len(blob) <= 1800 else blob[:1800] + "\n…(truncated)"
            rpt.add_field(name="Contents", value=f"```txt\n{show}\n```", inline=False)

        items = list_items_recursive(category)
        roles = {r.id for r in interaction.user.roles}
        owner_admin = (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator)
        items = [i for i in items if has_access(category, i, roles, owner_admin)[0]]
        select_another = Select(
            placeholder="Select another item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1,
            custom_id="cat_item_select_again_v5"
        )
        async def _again(inter2: nextcord.Interaction):
            await self.on_item(inter2)
        select_another.callback = _again

        back = Button(label="← Back to list", style=ButtonStyle.secondary, custom_id="back_to_list_v5")
        async def on_back(inter2: nextcord.Interaction):
            embed2, view2 = self.build_item_list_view(category, inter2.user)
            await inter2.response.edit_message(embed=embed2, view=view2)
        back.callback = on_back

        view = View(timeout=None)
        view.bot = self.bot
        view.add_item(select_another)
        view.add_item(back)
        await interaction.response.edit_message(embed=rpt, view=view)

    async def on_item(self, interaction: nextcord.Interaction):
        category = self.category or list_categories()[0]
        item_rel_base = interaction.data["values"][0]
        await self.show_item(interaction, category, item_rel_base)


class RootView(View):
    def __init__(self, bot: nextcord.Client, intro_title: str, intro_desc: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(CategorySelect(bot))
        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary, custom_id="refresh_root_v5")
        refresh.callback = self.refresh_menu
        self.add_item(refresh)

        search_btn = Button(label="🔎 Search", style=ButtonStyle.secondary, custom_id="search_open_v3")
        async def open_search(inter: nextcord.Interaction):
            await inter.response.send_modal(SearchModal(self.bot))
        search_btn.callback = open_search
        self.add_item(search_btn)
        self._intro_title = intro_title
        self._intro_desc = intro_desc

    async def refresh_menu(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title=self._intro_title, description=self._intro_desc, color=0x00FFCC),
            view=RootView(self.bot, self._intro_title, self._intro_desc)
        )


class SearchModal(nextcord.ui.Modal):
    def __init__(self, bot: nextcord.Client):
        super().__init__(title="Search Files")
        self.bot = bot
        self.query = nextcord.ui.TextInput(label="Query", placeholder="keywords (case-insensitive)", min_length=1, max_length=100)
        self.add_item(self.query)

    async def callback(self, interaction: nextcord.Interaction):
        q = self.query.value.strip().lower()
        results = []
        for cat in list_categories():
            for item in list_items_recursive(cat):
                if q in item.lower():
                    results.append((cat, item))
        if not results:
            return await interaction.response.send_message("No matches.", ephemeral=True)
        opts = [SelectOption(label=f"{c} / {i}", value=f"{c}|{i}") for c, i in results[:25]]
        sel = Select(placeholder="Search results…", options=opts, min_values=1, max_values=1, custom_id="search_select_v3")

        async def on_pick(inter2: nextcord.Interaction):
            cat, item = inter2.data["values"][0].split("|", 1)
            cat_select = CategorySelect(self.bot)
            cat_select.category = cat
            await cat_select.show_item(inter2, cat, item)

        sel.callback = on_pick
        v = View(timeout=None)
        v.bot = self.bot
        v.add_item(sel)
        await interaction.response.send_message("Select a result:", view=v, ephemeral=True)
