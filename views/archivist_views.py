import datetime, json, traceback, nextcord
from nextcord import Embed, SelectOption, ButtonStyle, TextInputStyle
from nextcord.ui import View, Select, Button, Modal, TextInput

# Altijd via utils.*
from utils.file_ops import (
    list_categories, list_items_recursive,
    create_dossier_file, remove_dossier_file,
    update_dossier_raw, patch_dossier_json_field,
    get_required_roles, _find_existing_item_key,
    grant_file_clearance
)
from storage_spaces import read_json, read_text, list_dir, save_text, ensure_dir
from utils.logging_utils import log_action
from config import ALLOWED_ASSIGN_ROLES, BACKUP_DIR

# Hardcoded rollen (zoals gevraagd)
try:
    from config import LEAD_ARCHIVIST_ROLE_ID as _LEAD_ARCH_ID
except Exception:
    _LEAD_ARCH_ID = 1405932476089765949
try:
    from config import ARCHIVIST_ROLE_ID as _ARCHIVIST_ID
except Exception:
    _ARCHIVIST_ID = 1405757611919544360

def _roles(user: nextcord.Member) -> set[int]:
    return {r.id for r in user.roles}

def _is_owner_admin(user: nextcord.Member) -> bool:
    return user.id == user.guild.owner_id or user.guild_permissions.administrator

def _is_lead(user: nextcord.Member) -> bool:
    rs = _roles(user)
    return _is_owner_admin(user) or (_LEAD_ARCH_ID in rs)

def _is_archivist(user: nextcord.Member) -> bool:
    rs = _roles(user)
    return _is_lead(user) or (_ARCHIVIST_ID in rs)


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
            placeholder="Paste JSON or plain text here…",
            style=TextInputStyle.paragraph,
            min_length=1, max_length=4000
        )
        self.add_item(self.item)
        self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            category = self.parent_view.category
            role_id  = self.parent_view.role_id
            item_rel = self.item.value.strip()
            content  = self.content.value

            if not category:
                return await interaction.response.send_message("Select a category first.", ephemeral=True)
            if not role_id:
                return await interaction.response.send_message("Select a clearance role first.", ephemeral=True)

            key = create_dossier_file(category, item_rel, content)
            grant_file_clearance(category, item_rel.strip().strip("/"), int(role_id))

            await log_action(interaction.client, f"⬆️ {interaction.user} uploaded `{category}/{item_rel}` with default role <@&{role_id}>.")
            await interaction.response.send_message(
                f"✅ Created `{category}/{item_rel}` with default clearance <@&{role_id}>.",
                ephemeral=True
            )
        except FileExistsError:
            await interaction.response.send_message("⚠️ File already exists.", ephemeral=True)
        except Exception as e:
            await log_action(interaction.client, f"❗ UploadDetailsModal error: {e}\n```{traceback.format_exc()[:1800]}```")
            try:
                await interaction.response.send_message("❌ Failed to create file (see log).", ephemeral=True)
            except:
                await interaction.followup.send("❌ Failed to create file (see log).", ephemeral=True)


class UploadFileView(View):
    def __init__(self, bot: nextcord.Client):
        super().__init__(timeout=None)
        self.bot = bot
        self.category = None
        self.role_id  = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1, custom_id="upload_cat_v5"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        # filter op toegestane rollen
        guild_roles = {r.id: r for r in interaction.guild.roles}
        roles = []
        for rid in ALLOWED_ASSIGN_ROLES:
            r = guild_roles.get(int(rid))
            if r: roles.append(r)
        if not roles:
            return await interaction.response.send_message("No assignable roles configured.", ephemeral=True)
        sel_role = Select(
            placeholder="Step 2: Select default clearance…",
            options=[SelectOption(label=r.name, value=str(r.id)) for r in roles],
            min_values=1, max_values=1, custom_id="upload_role_v5"
        )
        sel_role.callback = self.select_role
        self.add_item(sel_role)

        submit = Button(label="Step 3: Enter file details", style=ButtonStyle.primary, custom_id="upload_modal_v5")
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
        self.category = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1, custom_id="rm_cat_v5"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.send_message("No files in this category.", ephemeral=True)
        sel_item = Select(
            placeholder="Step 2: Select file…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1, custom_id="rm_item_v5"
        )
        async def choose_item(inter2: nextcord.Interaction):
            try:
                remove_dossier_file(self.category, inter2.data["values"][0])
                await log_action(self.bot, f"🗑 {inter2.user} removed `{self.category}/{inter2.data['values'][0]}`.")
                await inter2.response.send_message("✅ Removed.", ephemeral=True)
            except FileNotFoundError:
                await inter2.response.send_message("❌ File not found.", ephemeral=True)
            except Exception as e:
                await log_action(self.bot, f"❗ remove error: {e}\n```{traceback.format_exc()[:1800]}```")
                await inter2.response.send_message("❌ Remove failed (see log).", ephemeral=True)
        sel_item.callback = choose_item
        self.add_item(sel_item)

        await interaction.response.edit_message(
            embed=Embed(title="Remove File", description=f"Category: **{self.category}**\nSelect file to delete…", color=0xFF5555),
            view=self,
        )


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
        if not _is_lead(interaction.user):
            return await interaction.response.send_message("⛔ Lead Archivist only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Remove File", description="Step 1: Select category…", color=0xFF5555),
            view=RemoveFileView(self.bot), ephemeral=True
        )

    async def backup_now(self, interaction: nextcord.Interaction):
        if not _is_lead(interaction.user):
            return await interaction.response.send_message("⛔ Lead Archivist only.", ephemeral=True)
        ts = await _backup_now(self.bot)
        await interaction.response.send_message(f"✅ Backup manifest created: `{ts}`", ephemeral=True)

    async def refresh(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title="Archivist Console", description="Select an action below.", color=0x00FFCC),
            view=ArchivistConsoleView(self.bot, interaction.user)
        )

async def _backup_now(bot: nextcord.Client) -> str:
    # Maak manifest in _backups (nooit zichtbaar in UI)
    from config import ROOT_PREFIX
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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
            if "/_versions/" in key or f"{ROOT_PREFIX}/_backups" in key or "/acl/" in key:
                continue
            manifest["files"].append(key)
    ensure_dir(BACKUP_DIR)
    save_text(f"{BACKUP_DIR}/{ts}-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return ts
