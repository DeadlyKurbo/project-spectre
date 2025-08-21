import json, traceback, nextcord
from nextcord import Embed, SelectOption, ButtonStyle, TextInputStyle
from nextcord.ui import View, Select, Button, Modal, TextInput

from config import ALLOWED_ASSIGN_ROLES
from utils.file_ops import (
    list_categories, list_items_recursive,
    create_dossier_file, remove_dossier_file,
    update_dossier_raw, patch_dossier_json_field,
    get_required_roles, _find_existing_item_key
)
from utils.logging_utils import log_action
from storage_spaces import read_json, read_text

def _is_archivist(user: nextcord.Member) -> bool:
    user_roles = {r.id for r in user.roles}
    return (
        user.id == user.guild.owner_id
        or user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    )

class UploadDetailsModal(Modal):
    def __init__(self, parent_view: "UploadFileView"):
        super().__init__(title="Archive Upload")
        self.parent_view = parent_view
        self.item = TextInput(
            label="File path",
            placeholder="e.g. intel/hoot_alliance (ext optional)",
            min_length=1, max_length=4000
        )
        self.content = TextInput(
            label="Content",
            placeholder="Paste JSON or plain text",
            style=TextInputStyle.paragraph,
            min_length=1, max_length=4000
        )
        self.add_item(self.item); self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            role_id = getattr(self.parent_view, "role_id", None)
            if role_id is None:
                return await interaction.response.send_message("❌ Select a clearance role first.", ephemeral=True)
            item_rel = self.item.value.strip().lower().replace(" ", "_").strip("/")
            content  = self.content.value
            key = create_dossier_file(self.parent_view.category, item_rel, content, prefer_txt_default=True)
            item_base = item_rel.rsplit(".", 1)[0]
            from utils.file_ops import grant_file_clearance
            grant_file_clearance(self.parent_view.category, item_base, int(role_id))
            await interaction.response.send_message(
                f"✅ Uploaded `{self.parent_view.category}/{item_rel}` with clearance <@&{role_id}>.",
                ephemeral=True,
            )
            await log_action(self.parent_view.bot, f"⬆️ {interaction.user} uploaded `{self.parent_view.category}/{item_rel}` with clearance <@&{role_id}>.")
        except FileExistsError:
            await interaction.response.send_message("❌ File already exists.", ephemeral=True)
        except Exception as e:
            await log_action(self.parent_view.bot, f"❗ Upload modal error: {e}\n```{traceback.format_exc()[:1800]}```")
            try:
                await interaction.response.send_message("❌ Upload failed (see log).", ephemeral=True)
            except Exception:
                await interaction.followup.send("❌ Upload failed (see log).", ephemeral=True)

class UploadFileView(View):
    def __init__(self, bot: nextcord.Client):
        super().__init__(timeout=None)
        self.bot = bot
        self.category = None
        self.role_id  = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1, custom_id="upload_cat_v3"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        roles = [r for r in interaction.guild.roles if r.id in ALLOWED_ASSIGN_ROLES]
        if not roles:
            return await interaction.response.edit_message(
                embed=Embed(title="Upload File", description="No assignable clearance roles configured.", color=0xFF5555),
                view=self,
            )
        sel_role = Select(
            placeholder="Step 2: Select clearance role…",
            options=[SelectOption(label=r.name, value=str(r.id)) for r in roles],
            min_values=1, max_values=1, custom_id="upload_role_v3"
        )
        sel_role.callback = self.select_role
        self.add_item(sel_role)

        submit = Button(label="Step 3: Enter file details", style=ButtonStyle.primary, custom_id="upload_modal_v3")
        async def open_modal(inter2: nextcord.Interaction):
            try: await inter2.response.send_modal(UploadDetailsModal(self))
            except Exception as e:
                await log_action(self.bot, f"❗ open_modal error: {e}\n```{traceback.format_exc()[:1800]}```")
                try:    await inter2.response.send_message("❌ Could not open modal (see log).", ephemeral=True)
                except: await inter2.followup.send("❌ Could not open modal (see log).", ephemeral=True)
        submit.callback = open_modal
        self.add_item(submit)

        await interaction.response.edit_message(
            embed=Embed(title="Upload File", description=f"Category: **{self.category}**\nSelect role and enter details…", color=0x00FFCC),
            view=self,
        )

    async def select_role(self, interaction: nextcord.Interaction):
        self.role_id = int(interaction.data["values"][0])
        await interaction.response.send_message(f"Clearance role set to <@&{self.role_id}>.", ephemeral=True)

class RemoveFileView(View):
    def __init__(self, bot: nextcord.Client):
        super().__init__(timeout=None)
        self.bot = bot
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_", " ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1, custom_id="remove_cat_v3"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(title="Remove File", description=f"Category: **{self.category}**\n(No files found)", color=0xFF5555), view=self
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1, custom_id="remove_item_v3"
        )
        sel_item.callback = self.delete_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(title="Remove File", description=f"Category: **{self.category}**\nSelect an item…", color=0xFF5555),
            view=self,
        )

    async def delete_item(self, interaction: nextcord.Interaction):
        item_rel_base = interaction.data["values"][0]
        try:
            remove_dossier_file(self.category, item_rel_base)
        except FileNotFoundError:
            return await interaction.response.send_message("❌ File not found.", ephemeral=True)
        await interaction.response.send_message(f"🗑️ Deleted `{self.category}/{item_rel_base}`.", ephemeral=True)
        await log_action(self.bot, f"🗑 {interaction.user} deleted `{self.category}/{item_rel_base}`.")

class GrantClearanceView(View):
    def __init__(self, bot: nextcord.Client):
        super().__init__(timeout=None)
        self.bot = bot
        self.category = None
        self.item     = None
        self.roles_to_add: list[int] = []
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1, custom_id="grant_cat_v1"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(title="Grant Clearance", description=f"Category: **{self.category}**\n(No files found)", color=0x00FFCC), view=self
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1, custom_id="grant_item_v1"
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(title="Grant Clearance", description=f"Category: **{self.category}**\nSelect an item…", color=0x00FFCC),
            view=self,
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()

        current = get_required_roles(self.category, self.item)
        roles = [r for r in interaction.guild.roles if r.id in ALLOWED_ASSIGN_ROLES]
        if not roles:
            return await interaction.response.edit_message(
                embed=Embed(title="Grant Clearance", description="No assignable roles configured.", color=0xFFAA00), view=self
            )
        sel_roles = Select(
            placeholder="Step 3: Select roles to GRANT…",
            options=[SelectOption(label=r.name, value=str(r.id), default=(r.id in current)) for r in roles],
            min_values=1, max_values=min(5, len(roles)), custom_id="grant_roles_v1"
        )
        async def choose_roles(inter2: nextcord.Interaction):
            self.roles_to_add = [int(v) for v in inter2.data["values"]]
            await inter2.response.send_message("Roles selected.", ephemeral=True)
        sel_roles.callback = choose_roles
        self.add_item(sel_roles)

        apply_btn = Button(label="Apply Grants", style=ButtonStyle.success, custom_id="apply_grant_v1")
        async def do_grant(inter2: nextcord.Interaction):
            if not self.roles_to_add:
                return await inter2.response.send_message("Select at least one role.", ephemeral=True)
            from utils.file_ops import grant_file_clearance
            for rid in self.roles_to_add:
                grant_file_clearance(self.category, self.item, rid)
            await inter2.response.send_message(
                f"✅ Granted: {', '.join(f'<@&{r}>' for r in self.roles_to_add)} → `{self.category}/{self.item}`",
                ephemeral=True
            )
            await log_action(self.bot, f"🟩 {inter2.user} granted {self.roles_to_add} on `{self.category}/{self.item}`.")
        apply_btn.callback = do_grant
        self.add_item(apply_btn)

        cancel = Button(label="← Back", style=ButtonStyle.secondary, custom_id="grant_back_v1")
        async def go_back(inter2: nextcord.Interaction):
            self.__init__(self.bot)  # reset
            await inter2.response.edit_message(
                embed=Embed(title="Grant Clearance", description="Step 1: Select category…", color=0x00FFCC),
                view=self
            )
        cancel.callback = go_back
        self.add_item(cancel)

        curr_names = [f"<@&{r}>" for r in current] if current else ["None (public)"]
        embed = Embed(title="Grant Clearance", color=0x00FFCC)
        embed.add_field(name="File", value=f"`{self.category}/{self.item}`", inline=False)
        embed.add_field(name="Current clearance", value=", ".join(curr_names), inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

class RevokeClearanceView(View):
    def __init__(self, bot: nextcord.Client):
        super().__init__(timeout=None)
        self.bot = bot
        self.category = None
        self.item     = None
        self.roles_to_remove: list[int] = []
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1, custom_id="revoke_cat_v1"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(title="Revoke Clearance", description=f"Category: **{self.category}**\n(No files found)", color=0xFF5555), view=self
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1, custom_id="revoke_item_v1"
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(title="Revoke Clearance", description=f"Category: **{self.category}**\nSelect an item…", color=0xFF5555),
            view=self,
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()

        current = list(get_required_roles(self.category, self.item))
        if not current:
            return await interaction.response.edit_message(
                embed=Embed(title="Revoke Clearance", description="File is public; nothing to revoke.", color=0xFFAA00), view=self
            )
        options = []
        for rid in current:
            role = nextcord.utils.get(interaction.guild.roles, id=rid)
            label = role.name if role else str(rid)
            options.append(SelectOption(label=label, value=str(rid)))
        sel_roles = Select(
            placeholder="Step 3: Select roles to REVOKE…",
            options=options, min_values=1, max_values=min(5, len(options)), custom_id="revoke_roles_v1"
        )
        async def choose_roles(inter2: nextcord.Interaction):
            self.roles_to_remove = [int(v) for v in inter2.data["values"]]
            await inter2.response.send_message("Roles selected.", ephemeral=True)
        sel_roles.callback = choose_roles
        self.add_item(sel_roles)

        apply_btn = Button(label="Apply Revokes", style=ButtonStyle.danger, custom_id="apply_revoke_v1")
        async def do_revoke(inter2: nextcord.Interaction):
            if not self.roles_to_remove:
                return await inter2.response.send_message("Select at least one role.", ephemeral=True)
            from utils.file_ops import revoke_file_clearance
            for rid in self.roles_to_remove:
                revoke_file_clearance(self.category, self.item, rid)
            await inter2.response.send_message(
                f"✅ Revoked: {', '.join(f'<@&{r}>' for r in self.roles_to_remove)} ← `{self.category}/{self.item}`",
                ephemeral=True
            )
            await log_action(self.bot, f"🟥 {inter2.user} revoked {self.roles_to_remove} on `{self.category}/{self.item}`.")
        apply_btn.callback = do_revoke
        self.add_item(apply_btn)

        cancel = Button(label="← Back", style=ButtonStyle.secondary, custom_id="revoke_back_v1")
        async def go_back(inter2: nextcord.Interaction):
            self.__init__(self.bot)  # reset
            await inter2.response.edit_message(
                embed=Embed(title="Revoke Clearance", description="Step 1: Select category…", color=0xFF5555),
                view=self
            )
        cancel.callback = go_back
        self.add_item(cancel)

        curr_names = [f"<@&{r}>" for r in current]
        embed = Embed(title="Revoke Clearance", color=0xFF5555)
        embed.add_field(name="File", value=f"`{self.category}/{self.item}`", inline=False)
        embed.add_field(name="Current clearance", value=", ".join(curr_names), inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

class EditRawModal(Modal):
    def __init__(self, parent_view: "EditFileView", current_text: str):
        super().__init__(title="Edit File (Raw)")
        self.parent_view = parent_view
        self.content = TextInput(
            label="New content",
            style=TextInputStyle.paragraph,
            default_value=current_text[:4000],
            min_length=1, max_length=4000
        )
        self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            key = update_dossier_raw(self.parent_view.category, self.parent_view.item, self.content.value)
            await interaction.response.send_message(f"✅ Saved raw changes to `{self.parent_view.category}/{self.parent_view.item}`.\n`{key}`", ephemeral=True)
            await log_action(self.parent_view.bot, f"✏️ {interaction.user} edited RAW `{self.parent_view.category}/{self.parent_view.item}`.")
        except FileNotFoundError:
            await interaction.response.send_message("❌ File not found.", ephemeral=True)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except Exception as e:
            await log_action(self.parent_view.bot, f"❗ EditRawModal error: {e}\n```{traceback.format_exc()[:1800]}```")
            try:
                await interaction.response.send_message("❌ Save failed (see log).", ephemeral=True)
            except Exception:
                await interaction.followup.send("❌ Save failed (see log).", ephemeral=True)

class PatchFieldModal(Modal):
    def __init__(self, parent_view: "EditFileView"):
        super().__init__(title="Patch JSON Field")
        self.parent_view = parent_view
        self.field = TextInput(
            label="Field path (dot.notation)",
            placeholder="e.g. status or metadata.phase",
            min_length=1, max_length=300
        )
        self.value = TextInput(
            label="New value",
            placeholder='Examples: "Operation finished"  |  42  |  true  |  {"k":"v"}',
            style=TextInputStyle.paragraph,
            min_length=1, max_length=2000
        )
        self.add_item(self.field); self.add_item(self.value)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            key = patch_dossier_json_field(self.parent_view.category, self.parent_view.item, self.field.value.strip(), self.value.value.strip())
            await interaction.response.send_message(
                f"✅ Patched `{self.field.value.strip()}` on `{self.parent_view.category}/{self.parent_view.item}`.\n`{key}`",
                ephemeral=True
            )
            await log_action(self.parent_view.bot, f"🛠 {interaction.user} patched `{self.field.value.strip()}` on `{self.parent_view.category}/{self.parent_view.item}`.")
        except FileNotFoundError:
            await interaction.response.send_message("❌ File not found.", ephemeral=True)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except Exception as e:
            await log_action(self.parent_view.bot, f"❗ PatchFieldModal error: {e}\n```{traceback.format_exc()[:1800]}```")
            try:
                await interaction.response.send_message("❌ Patch failed (see log).", ephemeral=True)
            except Exception:
                await interaction.followup.send("❌ Patch failed (see log).", ephemeral=True)

class EditFileView(View):
    def __init__(self, bot: nextcord.Client):
        super().__init__(timeout=None)
        self.bot = bot
        self.category = None
        self.item     = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1, custom_id="edit_cat_v1"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(title="Edit File", description=f"Category: **{self.category}**\n(No files found)", color=0x00FFCC),
                view=self
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1, custom_id="edit_item_v1"
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(title="Edit File", description=f"Category: **{self.category}**\nSelect an item…", color=0x00FFCC),
            view=self
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()

        found = _find_existing_item_key(self.category, self.item)
        if not found:
            return await interaction.response.edit_message(
                embed=Embed(title="Edit File", description="File not found.", color=0xFF5555), view=self
            )
        key, ext = found
        preview = ""
        try:
            if ext == ".json":
                data = read_json(key)
                preview = json.dumps(data, ensure_ascii=False, indent=2)
            else:
                preview = read_text(key)
        except Exception:
            preview = "(Could not read file)"
        short = preview if len(preview) <= 1000 else preview[:1000] + "\n…(truncated)"

        required = get_required_roles(self.category, self.item)
        curr_names = [f"<@&{r}>" for r in required] if required else ["None (public)"]

        embed = Embed(title="Edit File", color=0x00FFCC)
        embed.add_field(name="File", value=f"`{self.category}/{self.item}{ext}`", inline=False)
        embed.add_field(name="Current clearance", value=", ".join(curr_names), inline=False)
        embed.add_field(name="Preview", value=f"```json\n{short}\n```" if ext == ".json" else f"```txt\n{short}\n```", inline=False)

        btn_raw = Button(label="✏️ Edit Raw", style=ButtonStyle.primary, custom_id="edit_raw_v1")
        async def open_raw(inter2: nextcord.Interaction):
            try:
                await inter2.response.send_modal(EditRawModal(self, preview))
            except Exception as e:
                await log_action(self.bot, f"❗ open_raw error: {e}\n```{traceback.format_exc()[:1800]}```")
                try:    await inter2.response.send_message("❌ Could not open modal (see log).", ephemeral=True)
                except: await inter2.followup.send("❌ Could not open modal (see log).", ephemeral=True)
        btn_raw.callback = open_raw

        btn_patch = Button(label="🛠 Patch JSON Field", style=ButtonStyle.success, custom_id="patch_field_v1")
        async def open_patch(inter2: nextcord.Interaction):
            try:
                await inter2.response.send_modal(PatchFieldModal(self))
            except Exception as e:
                await log_action(self.bot, f"❗ open_patch error: {e}\n```{traceback.format_exc()[:1800]}```")
                try:    await inter2.response.send_message("❌ Could not open modal (see log).", ephemeral=True)
                except: await inter2.followup.send("❌ Could not open modal (see log).", ephemeral=True)
        btn_patch.callback = open_patch

        btn_back = Button(label="← Back", style=ButtonStyle.secondary, custom_id="edit_back_v1")
        async def go_back(inter2: nextcord.Interaction):
            self.__init__(self.bot)
            await inter2.response.edit_message(
                embed=Embed(title="Edit File", description="Step 1: Select category…", color=0x00FFCC),
                view=self
            )
        btn_back.callback = go_back

        self.add_item(btn_raw); self.add_item(btn_patch); self.add_item(btn_back)
        await interaction.response.edit_message(embed=embed, view=self)

class ArchivistConsoleView(View):
    def __init__(self, bot: nextcord.Client, user: nextcord.Member):
        super().__init__(timeout=None)
        self.bot = bot
        self.user = user

        self.btn_upload = Button(label="📤 Upload File", style=ButtonStyle.primary)
        self.btn_upload.callback = self.open_upload
        self.add_item(self.btn_upload)

        self.btn_remove = Button(label="🗑 Remove File", style=ButtonStyle.danger)
        self.btn_remove.callback = self.open_remove
        self.add_item(self.btn_remove)

        self.btn_grant  = Button(label="🟩 Grant Clearance", style=ButtonStyle.success)
        self.btn_grant.callback = self.open_grant
        self.add_item(self.btn_grant)

        self.btn_revoke = Button(label="🟥 Revoke Clearance", style=ButtonStyle.danger)
        self.btn_revoke.callback = self.open_revoke
        self.add_item(self.btn_revoke)

        self.btn_edit = Button(label="✏️ Edit File", style=ButtonStyle.primary)
        self.btn_edit.callback = self.open_edit
        self.add_item(self.btn_edit)

        self.btn_refresh = Button(label="🔄 Refresh", style=ButtonStyle.secondary)
        self.btn_refresh.callback = self.refresh
        self.add_item(self.btn_refresh)

        self.btn_backup = Button(label="🧰 Backup Now", style=ButtonStyle.secondary)
        self.btn_backup.callback = self.backup_now
        self.add_item(self.btn_backup)

    async def open_upload(self, interaction: nextcord.Interaction):
        if not _is_archivist(interaction.user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Upload File", description="Step 1: Select category…", color=0x00FFCC),
            view=UploadFileView(self.bot), ephemeral=True
        )

    async def open_remove(self, interaction: nextcord.Interaction):
        if not _is_archivist(interaction.user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Remove File", description="Step 1: Select category…", color=0xFF5555),
            view=RemoveFileView(self.bot), ephemeral=True
        )

    async def open_grant(self, interaction: nextcord.Interaction):
        if not _is_archivist(interaction.user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Grant Clearance", description="Step 1: Select category…", color=0x00FFCC),
            view=GrantClearanceView(self.bot), ephemeral=True
        )

    async def open_revoke(self, interaction: nextcord.Interaction):
        if not _is_archivist(interaction.user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Revoke Clearance", description="Step 1: Select category…", color=0xFF5555),
            view=RevokeClearanceView(self.bot), ephemeral=True
        )

    async def open_edit(self, interaction: nextcord.Interaction):
        if not _is_archivist(interaction.user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Edit File", description="Step 1: Select category…", color=0x00FFCC),
            view=EditFileView(self.bot), ephemeral=True
        )

    async def backup_now(self, interaction: nextcord.Interaction):
        if not _is_archivist(interaction.user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
        ts = await _backup_now(self.bot)
        await interaction.response.send_message(f"✅ Backup manifest created: `{ts}`", ephemeral=True)

    async def refresh(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(
                title="Archivist Console",
                description="Select an action below.",
                color=0x00FFCC
            ),
            view=ArchivistConsoleView(self.bot, interaction.user)
        )


from config import BACKUP_DIR
from storage_spaces import list_dir, save_text, ensure_dir

async def _backup_now(bot: nextcord.Client) -> str:
    # Create a manifest of all files under ROOT_PREFIX (excl backups)
    from config import ROOT_PREFIX
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest = {"timestamp": ts, "files": []}
    stack = [ROOT_PREFIX]
    while stack:
        base = stack.pop()
        dirs, files = list_dir(base)
        for d in dirs:
            dname = d.strip("/")
            if dname == "_backups":
                continue
            stack.append(f"{base}/{dname}".replace("//","/"))
        for name, _sz in files:
            key = f"{base}/{name}".replace("//","/")
            if "/_versions/" in key or f"{ROOT_PREFIX}/_backups" in key:
                continue
            manifest["files"].append(key)
    ensure_dir(BACKUP_DIR)
    save_text(f"{BACKUP_DIR}/{ts}-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return ts
