import json
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, UTC

import nextcord
from nextcord import Embed, SelectOption, ButtonStyle, TextInputStyle
from nextcord.ui import View, Select, Button, Modal, TextInput

from constants import (
    ALLOWED_ASSIGN_ROLES,
    UPLOAD_CHANNEL_ID,
    ARCHIVIST_ROLE_ID,
    LEAD_ARCHIVIST_ROLE_ID,
    LEVEL1_ROLE_ID,
    LEVEL2_ROLE_ID,
    LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID,
    LEAD_NOTIFICATION_CHANNEL_ID,
)
from config import get_build_version, set_build_version
from dossier import (
    list_categories,
    list_items_recursive,
    create_dossier_file,
    remove_dossier_file,
    archive_dossier_file,
    update_dossier_raw,
    patch_dossier_json_field,
    _find_existing_item_key,
    _strip_ext,
    read_json,
    read_text,
)
from acl import (
    grant_file_clearance,
    revoke_file_clearance,
    get_required_roles,
)
import os
from storage_spaces import list_dir, delete_file
from annotations import add_file_annotation


# ======== Archivist helpers ========

BASIC_ASSIGN_ROLES = {
    LEVEL1_ROLE_ID,
    LEVEL2_ROLE_ID,
    LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID,
}

_EDIT_LOG: dict[int, list[datetime]] = defaultdict(list)


def _is_archivist(user: nextcord.Member) -> bool:
    user_roles = {r.id for r in user.roles}
    return (
        user.id == user.guild.owner_id
        or user.guild_permissions.administrator
        or ARCHIVIST_ROLE_ID in user_roles
        or LEAD_ARCHIVIST_ROLE_ID in user_roles
    )


def _is_lead_archivist(user: nextcord.Member) -> bool:
    user_roles = {r.id for r in user.roles}
    return (
        user.id == user.guild.owner_id
        or user.guild_permissions.administrator
        or LEAD_ARCHIVIST_ROLE_ID in user_roles
    )


class UploadDetailsModal(Modal):
    def __init__(self, parent_view: "UploadFileView"):
        super().__init__(title="Archive Upload")
        self.parent_view = parent_view
        self.item = TextInput(
            label="File path",
            placeholder="e.g. intel/hoot_alliance (ext optional)",
            min_length=1,
            max_length=4000,
        )
        self.content = TextInput(
            label="Content",
            placeholder="Paste JSON or plain text",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=4000,
        )
        self.add_item(self.item)
        self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            role_id = getattr(self.parent_view, "role_id", None)
            if role_id is None:
                return await interaction.response.send_message(
                    "❌ Select a clearance role first.", ephemeral=True
                )
            item_rel = self.item.value.strip().lower().replace(" ", "_").strip("/")
            content = self.content.value
            key = create_dossier_file(
                self.parent_view.category, item_rel, content, prefer_txt_default=True
            )
            item_base = _strip_ext(item_rel)
            grant_file_clearance(self.parent_view.category, item_base, role_id)
            await interaction.response.send_message(
                f"✅ Uploaded `{self.parent_view.category}/{item_rel}` with clearance <@&{role_id}>.",
                ephemeral=True,
            )
            import main
            await main.log_action(
                f"⬆️ {interaction.user} uploaded `{self.parent_view.category}/{item_rel}` with clearance <@&{role_id}>."
            )
        except FileExistsError:
            await interaction.response.send_message("❌ File already exists.", ephemeral=True)
        except Exception as e:
            import main
            await main.log_action(
                f"❗ Upload modal error: {e}\n```{traceback.format_exc()[:1800]}```"
            )
            try:
                await interaction.response.send_message(
                    "❌ Upload failed (see log).", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    "❌ Upload failed (see log).", ephemeral=True
                )


class UploadFileView(View):
    def __init__(self, allowed_roles: set[int] | None = None):
        super().__init__(timeout=None)
        self.category = None
        self.role_id = None
        self.allowed_roles = allowed_roles or ALLOWED_ASSIGN_ROLES
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="upload_cat_v3",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        roles = [r for r in interaction.guild.roles if r.id in self.allowed_roles]
        if not roles:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Upload File",
                    description="No assignable roles configured.",
                    color=0xFFAA00,
                ),
                view=self,
            )
        sel_role = Select(
            placeholder="Step 2: Select clearance role…",
            options=[SelectOption(label=r.name, value=str(r.id)) for r in roles],
            min_values=1,
            max_values=1,
            custom_id="upload_role_v3",
        )
        async def choose_role(inter2: nextcord.Interaction):
            self.role_id = int(inter2.data["values"][0])
            await inter2.response.send_message("Role selected.", ephemeral=True)
        sel_role.callback = choose_role
        self.add_item(sel_role)

        confirm = Button(label="Upload…", style=ButtonStyle.success, custom_id="upload_go_v3")
        async def open_modal(inter2: nextcord.Interaction):
            try:
                await inter2.response.send_modal(UploadDetailsModal(self))
            except Exception as e:
                import main
                await main.log_action(
                    f"❗ open_modal error: {e}\n```{traceback.format_exc()[:1800]}```"
                )
                try:
                    await inter2.response.send_message(
                        "❌ Could not open modal (see log).", ephemeral=True
                    )
                except Exception:
                    await inter2.followup.send(
                        "❌ Could not open modal (see log).", ephemeral=True
                    )
        confirm.callback = open_modal
        self.add_item(confirm)

        await interaction.response.edit_message(
            embed=Embed(
                title="Upload File",
                description=f"Category: **{self.category}**\nSelect clearance role…",
                color=0x00FFCC,
            ),
            view=self,
        )


class BuildVersionModal(Modal):
    def __init__(self):
        super().__init__(title="Set Build Version")
        self.version = TextInput(
            label="Build Version",
            placeholder="e.g. v2.3.1",
            default_value=get_build_version(),
            min_length=1,
            max_length=50,
        )
        self.add_item(self.version)

    async def callback(self, interaction: nextcord.Interaction):
        version = self.version.value.strip()
        set_build_version(version)
        await interaction.response.send_message(
            f"✅ Build version set to {version}.", ephemeral=True
        )
        import main
        await main.log_action(
            f"🛠 {interaction.user} set build version to {version}."
        )
        await main.update_status_message()


class LoadBackupView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.selected: str | None = None
        _dirs, files = list_dir("backups")
        if not files:
            self.add_item(Button(label="No backups found", disabled=True))
            return
        options = [
            SelectOption(label=f, value=f) for f, _ in sorted(files, key=lambda x: x[0], reverse=True)
        ]
        sel = Select(
            placeholder="Select backup…",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="load_backup_select",
        )
        sel.callback = self.select_backup
        self.add_item(sel)

        btn = Button(label="Restore", style=ButtonStyle.danger, custom_id="load_backup_go")
        btn.callback = self.restore
        self.add_item(btn)

    async def select_backup(self, interaction: nextcord.Interaction):
        self.selected = interaction.data["values"][0]
        await interaction.response.send_message("Backup selected.", ephemeral=True)

    async def restore(self, interaction: nextcord.Interaction):
        if not self.selected:
            return await interaction.response.send_message(
                "Select a backup first.", ephemeral=True
            )
        import main
        try:
            _restore_path = f"backups/{self.selected}"
            _restore_backup = getattr(main, "_restore_backup")
            _restore_backup(_restore_path)
        except Exception as e:
            await main.log_action(
                f"❗ Restore backup error: {e}\n``{traceback.format_exc()[:1800]}``"
            )
            return await interaction.response.send_message(
                "❌ Restore failed (see log).", ephemeral=True
            )
        await interaction.response.send_message(
            f"✅ Restored `{self.selected}`.", ephemeral=True
        )
        await main.log_action(
            f"♻️ {interaction.user} restored backup `{self.selected}`."
        )


class RemoveFileView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.category = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="remove_cat_v3",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Remove File",
                    description=f"Category: **{self.category}**\n(No files found)",
                    color=0xFF5555,
                ),
                view=self,
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="remove_item_v3",
        )
        sel_item.callback = self.delete_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Remove File",
                description=f"Category: **{self.category}**\nSelect an item…",
                color=0xFF5555,
            ),
            view=self,
        )

    async def delete_item(self, interaction: nextcord.Interaction):
        item_rel_base = interaction.data["values"][0]
        try:
            remove_dossier_file(self.category, item_rel_base)
        except FileNotFoundError:
            return await interaction.response.send_message(
                "❌ File not found.", ephemeral=True
            )
        await interaction.response.send_message(
            f"🗑️ Deleted `{self.category}/{item_rel_base}`.", ephemeral=True
        )
        import main
        await main.log_action(
            f"🗑 {interaction.user} deleted `{self.category}/{item_rel_base}`."
        )


class ArchiveReviewView(View):
    def __init__(self, archived_path: str):
        super().__init__(timeout=None)
        self.archived_path = archived_path

        keep_btn = Button(label="Keep Archived", style=ButtonStyle.secondary)
        keep_btn.callback = self.keep
        self.add_item(keep_btn)

        del_btn = Button(label="Delete", style=ButtonStyle.danger)
        del_btn.callback = self.delete
        self.add_item(del_btn)

        noop_btn = Button(label="Do Nothing", style=ButtonStyle.secondary)
        noop_btn.callback = self.noop
        self.add_item(noop_btn)

    async def _check_role(self, interaction: nextcord.Interaction) -> bool:
        if LEAD_ARCHIVIST_ROLE_ID and LEAD_ARCHIVIST_ROLE_ID not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message("⛔ Lead Archivist only.", ephemeral=True)
            return False
        return True

    async def keep(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        await interaction.response.send_message("✅ File kept archived.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    async def delete(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        delete_file(self.archived_path)
        await interaction.response.send_message("🗑️ Archived file deleted.", ephemeral=True)
        import main
        await main.log_action(f"🗑 {interaction.user} deleted archived `{self.archived_path}`.")
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    async def noop(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        await interaction.response.send_message("No action taken.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)


class ArchiveFileView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.category = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="archive_cat_v1",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Archive File",
                    description=f"Category: **{self.category}**\n(No files found)",
                    color=0x00FFCC,
                ),
                view=self,
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="archive_item_v1",
        )
        sel_item.callback = self.archive_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Archive File",
                description=f"Category: **{self.category}**\nSelect an item…",
                color=0x00FFCC,
            ),
            view=self,
        )

    async def archive_item(self, interaction: nextcord.Interaction):
        item_rel_base = interaction.data["values"][0]
        try:
            archived_path = archive_dossier_file(self.category, item_rel_base)
        except FileNotFoundError:
            return await interaction.response.send_message(
                "❌ File not found.", ephemeral=True
            )
        await interaction.response.send_message(
            f"📦 Archived `{self.category}/{item_rel_base}`.", ephemeral=True
        )
        import main
        await main.log_action(
            f"📦 {interaction.user} archived `{self.category}/{item_rel_base}`."
        )
        if LEAD_NOTIFICATION_CHANNEL_ID:
            channel = interaction.guild.get_channel(LEAD_NOTIFICATION_CHANNEL_ID)
            if not channel:
                try:
                    channel = await interaction.client.fetch_channel(LEAD_NOTIFICATION_CHANNEL_ID)
                except Exception:
                    channel = None
            if channel:
                mention = (
                    f"<@&{LEAD_ARCHIVIST_ROLE_ID}>" if LEAD_ARCHIVIST_ROLE_ID else "Lead Archivists"
                )
                view = ArchiveReviewView(archived_path)
                try:
                    await channel.send(
                        f"{mention} {interaction.user.mention} archived `{self.category}/{item_rel_base}`.",
                        view=view,
                    )
                except Exception:
                    pass

class GrantClearanceView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.category = None
        self.item = None
        self.roles_to_add: list[int] = []
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="grant_cat_v1",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Grant Clearance",
                    description=f"Category: **{self.category}**\n(No files found)",
                    color=0x00FFCC,
                ),
                view=self,
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="grant_item_v1",
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Grant Clearance",
                description=f"Category: **{self.category}**\nSelect an item…",
                color=0x00FFCC,
            ),
            view=self,
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()

        current = get_required_roles(self.category, self.item)
        roles = [r for r in interaction.guild.roles if r.id in ALLOWED_ASSIGN_ROLES]
        if not roles:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Grant Clearance",
                    description="No assignable roles configured.",
                    color=0xFFAA00,
                ),
                view=self,
            )
        sel_roles = Select(
            placeholder="Step 3: Select roles to GRANT…",
            options=[
                SelectOption(label=r.name, value=str(r.id), default=(r.id in current))
                for r in roles
            ],
            min_values=1,
            max_values=min(5, len(roles)),
            custom_id="grant_roles_v1",
        )
        async def choose_roles(inter2: nextcord.Interaction):
            self.roles_to_add = [int(v) for v in inter2.data["values"]]
            await inter2.response.send_message("Roles selected.", ephemeral=True)
        sel_roles.callback = choose_roles
        self.add_item(sel_roles)

        apply_btn = Button(label="Apply Grants", style=ButtonStyle.success, custom_id="apply_grant_v1")
        async def do_grant(inter2: nextcord.Interaction):
            if not self.roles_to_add:
                return await inter2.response.send_message(
                    "Select at least one role.", ephemeral=True
                )
            for rid in self.roles_to_add:
                grant_file_clearance(self.category, self.item, rid)
            await inter2.response.send_message(
                f"✅ Granted: {', '.join(f'<@&{r}>' for r in self.roles_to_add)} → `{self.category}/{self.item}`",
                ephemeral=True,
            )
            import main
            await main.log_action(
                f"🟩 {inter2.user} granted {self.roles_to_add} on `{self.category}/{self.item}`."
            )
        apply_btn.callback = do_grant
        self.add_item(apply_btn)

        cancel = Button(label="← Back", style=ButtonStyle.secondary, custom_id="grant_back_v1")
        async def go_back(inter2: nextcord.Interaction):
            await self.__init__()
            await inter2.response.edit_message(
                embed=Embed(
                    title="Grant Clearance",
                    description="Step 1: Select category…",
                    color=0x00FFCC,
                ),
                view=self,
            )
        cancel.callback = go_back
        self.add_item(cancel)

        curr_names = [f"<@&{r}>" for r in current] if current else ["None (public)"]
        embed = Embed(title="Grant Clearance", color=0x00FFCC)
        embed.add_field(
            name="File", value=f"`{self.category}/{self.item}`", inline=False
        )
        embed.add_field(
            name="Current clearance", value=", ".join(curr_names), inline=False
        )
        await interaction.response.edit_message(embed=embed, view=self)


class RevokeClearanceView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.category = None
        self.item = None
        self.roles_to_remove: list[int] = []
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="revoke_cat_v1",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Revoke Clearance",
                    description=f"Category: **{self.category}**\n(No files found)",
                    color=0xFF0000,
                ),
                view=self,
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="revoke_item_v1",
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Revoke Clearance",
                description=f"Category: **{self.category}**\nSelect an item…",
                color=0xFF0000,
            ),
            view=self,
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()

        current = get_required_roles(self.category, self.item)
        if not current:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Revoke Clearance",
                    description="This file is already public.",
                    color=0xFF0000,
                ),
                view=self,
            )
        roles = [r for r in interaction.guild.roles if r.id in current]
        sel_roles = Select(
            placeholder="Step 3: Select roles to REVOKE…",
            options=[SelectOption(label=r.name, value=str(r.id)) for r in roles],
            min_values=1,
            max_values=min(5, len(roles)),
            custom_id="revoke_roles_v1",
        )
        async def choose_roles(inter2: nextcord.Interaction):
            self.roles_to_remove = [int(v) for v in inter2.data["values"]]
            await inter2.response.send_message("Roles selected.", ephemeral=True)
        sel_roles.callback = choose_roles
        self.add_item(sel_roles)

        apply_btn = Button(label="Apply Revokes", style=ButtonStyle.danger, custom_id="apply_revoke_v1")
        async def do_revoke(inter2: nextcord.Interaction):
            if not self.roles_to_remove:
                return await inter2.response.send_message(
                    "Select at least one role.", ephemeral=True
                )
            for rid in self.roles_to_remove:
                revoke_file_clearance(self.category, self.item, rid)
            await inter2.response.send_message(
                f"✅ Revoked: {', '.join(f'<@&{r}>' for r in self.roles_to_remove)} → `{self.category}/{self.item}`",
                ephemeral=True,
            )
            import main
            await main.log_action(
                f"🟥 {inter2.user} revoked {self.roles_to_remove} on `{self.category}/{self.item}`."
            )
        apply_btn.callback = do_revoke
        self.add_item(apply_btn)

        cancel = Button(label="← Back", style=ButtonStyle.secondary, custom_id="revoke_back_v1")
        async def go_back(inter2: nextcord.Interaction):
            await self.__init__()
            await inter2.response.edit_message(
                embed=Embed(
                    title="Revoke Clearance",
                    description="Step 1: Select category…",
                    color=0xFF0000,
                ),
                view=self,
            )
        cancel.callback = go_back
        self.add_item(cancel)

        curr_names = [f"<@&{r}>" for r in current]
        embed = Embed(title="Revoke Clearance", color=0xFF0000)
        embed.add_field(
            name="File", value=f"`{self.category}/{self.item}`", inline=False
        )
        embed.add_field(
            name="Current clearance", value=", ".join(curr_names), inline=False
        )
        await interaction.response.edit_message(embed=embed, view=self)


class EditRawModal(Modal):
    def __init__(self, parent_view: "EditFileView", existing_content: str):
        super().__init__(title="Edit Raw Content")
        self.parent_view = parent_view
        self.content = TextInput(
            label="Raw content",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=4000,
            default=existing_content[:4000],
        )
        self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            if self.parent_view.limit_edits:
                now = datetime.now(UTC)
                history = [
                    t for t in _EDIT_LOG[self.parent_view.user.id] if now - t < timedelta(hours=1)
                ]
                if len(history) >= 5:
                    return await interaction.response.send_message(
                        "❌ Edit limit reached (5 per hour).", ephemeral=True
                    )
                history.append(now)
                _EDIT_LOG[self.parent_view.user.id] = history
            update_dossier_raw(
                self.parent_view.category,
                self.parent_view.item,
                self.content.value,
            )
            await interaction.response.send_message(
                "✅ File updated.", ephemeral=True
            )
            import main
            await main.log_action(
                f"✏️ {interaction.user} edited RAW `{self.parent_view.category}/{self.parent_view.item}`."
            )
        except Exception as e:
            import main
            await main.log_action(
                f"❗ EditRawModal error: {e}\n```{traceback.format_exc()[:1800]}```"
            )
            try:
                await interaction.response.send_message(
                    "❌ Update failed (see log).", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    "❌ Update failed (see log).", ephemeral=True
                )


class PatchFieldModal(Modal):
    def __init__(self, parent_view: "EditFileView"):
        super().__init__(title="Patch JSON Field")
        self.parent_view = parent_view
        self.field = TextInput(label="Field path", placeholder="e.g. stats.hits", min_length=1, max_length=200)
        self.value = TextInput(label="New value", style=TextInputStyle.paragraph, min_length=1, max_length=4000)
        self.add_item(self.field)
        self.add_item(self.value)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            if self.parent_view.limit_edits:
                now = datetime.now(UTC)
                history = [
                    t for t in _EDIT_LOG[self.parent_view.user.id] if now - t < timedelta(hours=1)
                ]
                if len(history) >= 5:
                    return await interaction.response.send_message(
                        "❌ Edit limit reached (5 per hour).", ephemeral=True
                    )
                history.append(now)
                _EDIT_LOG[self.parent_view.user.id] = history
            patch_dossier_json_field(
                self.parent_view.category,
                self.parent_view.item,
                self.field.value.strip(),
                self.value.value,
            )
            await interaction.response.send_message(
                "✅ Field patched.", ephemeral=True
            )
            import main
            await main.log_action(
                f"🛠 {interaction.user} patched `{self.field.value.strip()}` on `{self.parent_view.category}/{self.parent_view.item}`."
            )
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except Exception as e:
            import main
            await main.log_action(
                f"❗ PatchFieldModal error: {e}\n```{traceback.format_exc()[:1800]}```"
            )
            try:
                await interaction.response.send_message(
                    "❌ Patch failed (see log).", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    "❌ Patch failed (see log).", ephemeral=True
                )


class EditFileView(View):
    def __init__(self, user: nextcord.Member, limit_edits: bool = False):
        super().__init__(timeout=None)
        self.user = user
        self.limit_edits = limit_edits
        self.category = None
        self.item = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="edit_cat_v1",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Edit File",
                    description=f"Category: **{self.category}**\n(No files found)",
                    color=0x00FFCC,
                ),
                view=self,
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="edit_item_v1",
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Edit File",
                description=f"Category: **{self.category}**\nSelect an item…",
                color=0x00FFCC,
            ),
            view=self,
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()

        found = _find_existing_item_key(self.category, self.item)
        if not found:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Edit File", description="File not found.", color=0xFF5555
                ),
                view=self,
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
        embed.add_field(
            name="File", value=f"`{self.category}/{self.item}{ext}`", inline=False
        )
        embed.add_field(
            name="Current clearance", value=", ".join(curr_names), inline=False
        )
        embed.add_field(
            name="Preview",
            value=(
                f"```json\n{short}\n```"
                if ext == ".json"
                else f"```txt\n{short}\n```"
            ),
            inline=False,
        )

        btn_raw = Button(label="✏️ Edit Raw", style=ButtonStyle.primary, custom_id="edit_raw_v1")
        async def open_raw(inter2: nextcord.Interaction):
            try:
                await inter2.response.send_modal(EditRawModal(self, preview))
            except Exception as e:
                import main
                await main.log_action(
                    f"❗ open_raw error: {e}\n```{traceback.format_exc()[:1800]}```"
                )
                try:
                    await inter2.response.send_message(
                        "❌ Could not open modal (see log).", ephemeral=True
                    )
                except Exception:
                    await inter2.followup.send(
                        "❌ Could not open modal (see log).", ephemeral=True
                    )
        btn_raw.callback = open_raw

        btn_patch = Button(label="🛠 Patch JSON Field", style=ButtonStyle.success, custom_id="patch_field_v1")
        async def open_patch(inter2: nextcord.Interaction):
            try:
                await inter2.response.send_modal(PatchFieldModal(self))
            except Exception as e:
                import main
                await main.log_action(
                    f"❗ open_patch error: {e}\n```{traceback.format_exc()[:1800]}```"
                )
                try:
                    await inter2.response.send_message(
                        "❌ Could not open modal (see log).", ephemeral=True
                    )
                except Exception:
                    await inter2.followup.send(
                        "❌ Could not open modal (see log).", ephemeral=True
                    )
        btn_patch.callback = open_patch

        btn_back = Button(label="← Back", style=ButtonStyle.secondary, custom_id="edit_back_v1")
        async def go_back(inter2: nextcord.Interaction):
            await self.__init__(self.user, self.limit_edits)
            await inter2.response.edit_message(
                embed=Embed(
                    title="Edit File",
                    description="Step 1: Select category…",
                    color=0x00FFCC,
                ),
                view=self,
            )
        btn_back.callback = go_back

        self.add_item(btn_raw)
        self.add_item(btn_patch)
        self.add_item(btn_back)
        await interaction.response.edit_message(embed=embed, view=self)


class AnnotateModal(Modal):
    def __init__(self, parent_view: "AnnotateFileView"):
        super().__init__(title="Annotate File")
        self.parent_view = parent_view
        self.note = TextInput(
            label="Comment",
            style=TextInputStyle.paragraph,
            max_length=400,
        )
        self.add_item(self.note)

    async def callback(self, interaction: nextcord.Interaction):
        comment = self.note.value.strip()
        if not comment:
            return await interaction.response.send_message(
                "❌ Comment cannot be empty.", ephemeral=True
            )
        add_file_annotation(
            self.parent_view.category,
            self.parent_view.item,
            str(interaction.user),
            comment,
        )
        import main

        await main.log_action(
            f"🖊️ {interaction.user} annotated `{self.parent_view.category}/{self.parent_view.item}`: {comment}"
        )
        await interaction.response.send_message(
            f"✅ Added comment for `{self.parent_view.category}/{self.parent_view.item}`.",
            ephemeral=True,
        )


class AnnotateFileView(View):
    def __init__(self, user: nextcord.Member):
        super().__init__(timeout=None)
        self.user = user
        self.category = None
        self.item = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="annotate_cat_v1",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Annotate File",
                    description=f"Category: **{self.category}**\\n(No files found)",
                    color=0x00FFCC,
                ),
                view=self,
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="annotate_item_v1",
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Annotate File",
                description=f"Category: **{self.category}**\\nSelect an item…",
                color=0x00FFCC,
            ),
            view=self,
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        try:
            await interaction.response.send_modal(AnnotateModal(self))
        except Exception as e:
            import main

            await main.log_action(
                f"❗ annotate modal error: {e}\\n```{traceback.format_exc()[:1800]}```"
            )
            try:
                await interaction.response.send_message(
                    "❌ Could not open modal (see log).", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    "❌ Could not open modal (see log).", ephemeral=True
                )


class RequestEditModal(Modal):
    def __init__(self, user: nextcord.Member):
        super().__init__(title="Request Edit")
        self.user = user
        self.path = TextInput(label="File path", placeholder="category/item", min_length=1, max_length=200)
        self.reason = TextInput(label="Issue", style=TextInputStyle.paragraph, min_length=1, max_length=4000)
        self.add_item(self.path)
        self.add_item(self.reason)

    async def callback(self, interaction: nextcord.Interaction):
        path = self.path.value.strip().lower().replace(" ", "_").strip("/")
        if "/" not in path:
            return await interaction.response.send_message(
                "❌ Use format `category/item`.", ephemeral=True
            )
        category, item = path.split("/", 1)
        if not _find_existing_item_key(category, item):
            return await interaction.response.send_message(
                "❌ File not found.", ephemeral=True
            )
        note = self.reason.value.strip()
        channel = None
        if LEAD_NOTIFICATION_CHANNEL_ID:
            channel = interaction.guild.get_channel(LEAD_NOTIFICATION_CHANNEL_ID)
            if not channel:
                try:
                    channel = await interaction.client.fetch_channel(LEAD_NOTIFICATION_CHANNEL_ID)
                except Exception:
                    channel = None
        mention = (
            f"<@&{LEAD_ARCHIVIST_ROLE_ID}>" if LEAD_ARCHIVIST_ROLE_ID else "Lead Archivists"
        )
        if channel:
            try:
                await channel.send(
                    f"{mention} {interaction.user.mention} requested edit for `{category}/{item}`: {note}"
                )
            except Exception:
                pass
        await interaction.response.send_message("📝 Edit request sent.", ephemeral=True)
        import main
        await main.log_action(
            f"📝 {interaction.user} requested edit for `{category}/{item}`: {note}"
        )


class ArchivistConsoleView(View):
    """One-stop console for archivists; ephemeral."""

    def __init__(self, user: nextcord.Member):
        super().__init__(timeout=None)
        self.user = user

        self.btn_upload = Button(label="📤 Upload File", style=ButtonStyle.primary)
        self.btn_upload.callback = self.open_upload
        self.add_item(self.btn_upload)

        self.btn_remove = Button(label="🗑 Remove File", style=ButtonStyle.danger)
        self.btn_remove.callback = self.open_remove
        self.add_item(self.btn_remove)

        self.btn_grant = Button(label="🟩 Grant Clearance", style=ButtonStyle.success)
        self.btn_grant.callback = self.open_grant
        self.add_item(self.btn_grant)

        self.btn_revoke = Button(label="🟥 Revoke Clearance", style=ButtonStyle.danger)
        self.btn_revoke.callback = self.open_revoke
        self.add_item(self.btn_revoke)

        self.btn_edit = Button(label="✏️ Edit File", style=ButtonStyle.secondary)
        self.btn_edit.callback = self.open_edit
        self.add_item(self.btn_edit)

        self.btn_annotate = Button(label="🖊️ Annotate File", style=ButtonStyle.secondary)
        self.btn_annotate.callback = self.open_annotate
        self.add_item(self.btn_annotate)

        self.btn_build = Button(label="⚙️ Set Build", style=ButtonStyle.secondary)
        self.btn_build.callback = self.open_build
        self.add_item(self.btn_build)

        self.btn_backup = Button(label="📥 Load Backup", style=ButtonStyle.secondary)
        self.btn_backup.callback = self.open_backup
        self.add_item(self.btn_backup)

    async def open_upload(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title="Upload File", description="Step 1: Select category…", color=0x00FFCC),
            view=UploadFileView(),
        )

    async def open_remove(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title="Remove File", description="Step 1: Select category…", color=0xFF5555),
            view=RemoveFileView(),
        )

    async def open_grant(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title="Grant Clearance", description="Step 1: Select category…", color=0x00FFCC),
            view=GrantClearanceView(),
        )

    async def open_revoke(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title="Revoke Clearance", description="Step 1: Select category…", color=0xFF0000),
            view=RevokeClearanceView(),
        )

    async def open_edit(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title="Edit File", description="Step 1: Select category…", color=0x00FFCC),
            view=EditFileView(self.user),
        )

    async def open_annotate(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(
                title="Annotate File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=AnnotateFileView(self.user),
        )

    async def open_build(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(BuildVersionModal())

    async def open_backup(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(
                title="Load Backup",
                description="Select backup to restore…",
                color=0x00FFCC,
            ),
            view=LoadBackupView(),
        )


class ArchivistLimitedConsoleView(View):
    """Limited console for regular archivists; ephemeral."""

    def __init__(self, user: nextcord.Member):
        super().__init__(timeout=None)
        self.user = user

        self.btn_upload = Button(label="📤 Upload File", style=ButtonStyle.primary)
        self.btn_upload.callback = self.open_upload
        self.add_item(self.btn_upload)

        self.btn_archive = Button(label="📦 Archive File", style=ButtonStyle.secondary)
        self.btn_archive.callback = self.open_archive
        self.add_item(self.btn_archive)

        self.btn_edit = Button(label="✏️ Edit File", style=ButtonStyle.secondary)
        self.btn_edit.callback = self.open_edit
        self.add_item(self.btn_edit)

        self.btn_annotate = Button(label="🖊️ Annotate File", style=ButtonStyle.secondary)
        self.btn_annotate.callback = self.open_annotate
        self.add_item(self.btn_annotate)

        self.btn_request = Button(label="📝 Request Edit", style=ButtonStyle.secondary)
        self.btn_request.callback = self.open_request_edit
        self.add_item(self.btn_request)

    async def open_upload(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title="Upload File", description="Step 1: Select category…", color=0x00FFCC),
            view=UploadFileView(BASIC_ASSIGN_ROLES),
        )

    async def open_archive(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title="Archive File", description="Step 1: Select category…", color=0x00FFCC),
            view=ArchiveFileView(),
        )

    async def open_edit(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title="Edit File", description="Step 1: Select category…", color=0x00FFCC),
            view=EditFileView(self.user, limit_edits=True),
        )

    async def open_annotate(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(
                title="Annotate File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=AnnotateFileView(self.user),
        )

    async def open_request_edit(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(RequestEditModal(self.user))


async def handle_upload(message: nextcord.Message):
    category = (message.content or "").strip().lower().replace(" ", "_")
    if not category:
        return await message.channel.send("❌ Add the category name in the message text.")
    if category not in list_categories():
        return await message.channel.send(f"❌ Unknown category `{category}`.")

    processed = False
    for attachment in message.attachments:
        if not (
            attachment.filename.lower().endswith(".json")
            or attachment.filename.lower().endswith(".txt")
        ):
            continue
        data = (await attachment.read()).decode("utf-8", errors="replace")
        is_json = attachment.filename.lower().endswith(".json")
        item_rel_input = os.path.splitext(attachment.filename)[0] if is_json else attachment.filename
        try:
            key = create_dossier_file(
                category, item_rel_input, data, prefer_txt_default=not is_json
            )
        except FileExistsError:
            await message.channel.send(f"⚠️ `{item_rel_input}` already exists.")
        else:
            await message.channel.send(f"✅ Added `{item_rel_input}` to `{category}`.")
            import main
            await main.log_action(
                f"⬆️ {message.author} uploaded `{category}/{item_rel_input}` → `{key}`."
            )
            processed = True

    if not processed:
        await message.channel.send("❌ No .json/.txt files found in the upload.")
