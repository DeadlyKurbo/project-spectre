import json
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, UTC
import asyncio
import random
import time
import io
from uuid import uuid4

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
    LEVEL5_ROLE_ID,
    CLASSIFIED_ROLE_ID,
    LEAD_NOTIFICATION_CHANNEL_ID,
    REPORT_REPLY_CHANNEL_ID,
    ARCHIVIST_MENU_TIMEOUT,
    MENU_CHANNEL_ID,
    ROSTER_CHANNEL_ID,
    INTRO_TITLE,
    INTRO_DESC,
    TRAINEE_ROLE_ID,
    TRAINEE_ARCHIVIST_TITLE,
    TRAINEE_ARCHIVIST_DESC,
    CONTENT_MAX_LENGTH,
)
from config import get_build_version, set_build_version
from dossier import (
    list_categories,
    list_items_recursive,
    list_archived_categories,
    list_archived_items_recursive,
    create_dossier_file,
    remove_dossier_file,
    archive_dossier_file,
    restore_archived_file,
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
from storage_spaces import list_dir, delete_file, save_json, read_json as ss_read_json
from annotations import (
    add_file_annotation,
    update_file_annotation,
    remove_file_annotation,
    list_file_annotations,
)

from roster import send_roster
from views import RootView


# ======== Archivist helpers ========

BASIC_ASSIGN_ROLES = {
    LEVEL1_ROLE_ID,
    LEVEL2_ROLE_ID,
    LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID,
}

_EDIT_LOG: dict[int, list[datetime]] = defaultdict(list)
_last_edit_verified: dict[int, float] = {}

# ===== Trainee submission helpers =====
_TRAINEE_PREFIX = "trainee_submissions"
_CODENAMES = [
    "Falcon",
    "Viper",
    "Ghost",
    "Specter",
    "Titan",
    "Saber",
    "Raven",
    "Phantom",
    "Hunter",
    "Nomad",
    "Reaper",
    "Talon",
    "Outlaw",
    "Raptor",
    "Sentinel",
    "Paladin",
    "Wraith",
    "Maverick",
    "Bishop",
    "Oracle",
]


def _submission_key(user_id: int, status: str, sub_id: str) -> str:
    return f"{_TRAINEE_PREFIX}/{user_id}/{status}/{sub_id}.json"


def _save_submission(user_id: int, action: dict) -> str:
    task_type = action.get("type", "task").upper()
    # Collect existing IDs to avoid collisions
    _, files_pending = list_dir(f"{_TRAINEE_PREFIX}/{user_id}/pending")
    _, files_completed = list_dir(f"{_TRAINEE_PREFIX}/{user_id}/completed")
    existing = {os.path.splitext(name)[0] for name, _ in files_pending + files_completed}
    while True:
        codename = random.choice(_CODENAMES)
        number = random.randint(0, 99)
        sub_id = f"{task_type}-{codename}-{number:02d}"
        if sub_id not in existing:
            break
    data = {"id": sub_id, "user_id": user_id, "status": "pending", "action": action}
    save_json(_submission_key(user_id, "pending", sub_id), data)
    return sub_id


def _load_submission(user_id: int, sub_id: str, status: str = "pending") -> dict:
    return ss_read_json(_submission_key(user_id, status, sub_id))


def _complete_submission(
    user_id: int, sub_id: str, status: str, reason: str | None = None
) -> None:
    data = _load_submission(user_id, sub_id)
    data["status"] = status
    if reason is not None:
        data["reason"] = reason
    save_json(_submission_key(user_id, "completed", sub_id), data)
    delete_file(_submission_key(user_id, "pending", sub_id))


def _list_submissions(user_id: int, status: str) -> list[dict]:
    dirs, files = list_dir(f"{_TRAINEE_PREFIX}/{user_id}/{status}")
    subs: list[dict] = []
    for name, _size in files:
        sub_id = os.path.splitext(name)[0]
        try:
            subs.append(_load_submission(user_id, sub_id, status))
        except Exception:
            continue
    return subs


def _is_archivist(user: nextcord.Member) -> bool:
    user_roles = {r.id for r in user.roles}
    return (
        user.id == user.guild.owner_id
        or user.guild_permissions.administrator
        or ARCHIVIST_ROLE_ID in user_roles
        or LEAD_ARCHIVIST_ROLE_ID in user_roles
        or TRAINEE_ROLE_ID in user_roles
    )


def _is_lead_archivist(user: nextcord.Member) -> bool:
    user_roles = {r.id for r in user.roles}
    return (
        user.id == user.guild.owner_id
        or user.guild_permissions.administrator
        or LEAD_ARCHIVIST_ROLE_ID in user_roles
    )


def _removal_author_id(user: nextcord.Member) -> int | None:
    """Return author ID to enforce annotation removal permissions.

    Lead archivists may remove any note, so return ``None`` to disable the
    author check. Regular archivists must provide their own user ID.
    """
    return None if _is_lead_archivist(user) else user.id


async def _summon_menus(interaction: nextcord.Interaction) -> None:
    """Refresh the menu and roster channels with the latest views."""
    import main

    menu_ch = interaction.guild.get_channel(MENU_CHANNEL_ID)
    if menu_ch:
        try:
            await menu_ch.purge()
        except Exception:
            pass
        try:
            await menu_ch.send(
                embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
                view=RootView(),
            )
        except Exception:
            pass

    roster_ch = interaction.guild.get_channel(ROSTER_CHANNEL_ID)
    if roster_ch:
        try:
            await send_roster(roster_ch, roster_ch.guild)
        except Exception:
            pass

    await interaction.response.send_message("📣 Menus summoned.", ephemeral=True)
    await main.log_action(f"📣 {interaction.user.mention} summoned all menus.")


class UploadDetailsModal(Modal):
    def __init__(
        self,
        parent_view: "UploadFileView",
        item_rel: str | None = None,
        pages: list[str] | None = None,
        page: int = 1,
    ):
        super().__init__(title="Archive Upload")
        self.parent_view = parent_view
        self.item_rel = item_rel
        self.pages = pages or []
        self.page = page

        if self.item_rel is None:
            self.item = TextInput(
                label="File path",
                placeholder="e.g. intel/hoot_alliance (ext optional)",
                min_length=1,
                max_length=4000,
            )
            self.add_item(self.item)

        self.content = TextInput(
            label=f"Content (page {self.page})",
            placeholder="Paste JSON or plain text",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=CONTENT_MAX_LENGTH,
        )
        self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            role_id = getattr(self.parent_view, "role_id", None)
            if role_id is None:
                return await interaction.response.send_message(
                    "❌ Select a clearance role first.", ephemeral=True
                )

            if self.item_rel is None:
                self.item_rel = (
                    self.item.value.strip().lower().replace(" ", "_").strip("/")
                )

            self.pages.append(self.content.value)

            await interaction.response.send_message(
                "Page saved. Add another page or finish the upload.",
                view=UploadMoreView(self),
                ephemeral=True,
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


class UploadMoreView(View):
    """Prompt to continue upload across multiple pages."""

    def __init__(self, modal: UploadDetailsModal):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.modal = modal

        btn_more = Button(label="Add Page", style=ButtonStyle.secondary)
        btn_more.callback = self.add_page
        self.add_item(btn_more)

        btn_finish = Button(label="Finish Upload", style=ButtonStyle.success)
        btn_finish.callback = self.finish
        self.add_item(btn_finish)

    async def add_page(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(
            UploadDetailsModal(
                self.modal.parent_view,
                self.modal.item_rel,
                self.modal.pages,
                self.modal.page + 1,
            )
        )

    async def finish(self, interaction: nextcord.Interaction):
        role_id = getattr(self.modal.parent_view, "role_id", None)
        try:
            content = "".join(self.modal.pages)
            key = create_dossier_file(
                self.modal.parent_view.category,
                self.modal.item_rel,
                content,
                prefer_txt_default=True,
            )
            item_base = _strip_ext(self.modal.item_rel)
            grant_file_clearance(self.modal.parent_view.category, item_base, role_id)
            await interaction.response.send_message(
                f"✅ Uploaded `{self.modal.parent_view.category}/{self.modal.item_rel}` with clearance <@&{role_id}>.",
                ephemeral=True,
            )
            import main
            await main.log_action(
                f"⬆️ {interaction.user.mention} uploaded `{self.modal.parent_view.category}/{self.modal.item_rel}` with clearance <@&{role_id}>."
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
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
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
            f"🛠 {interaction.user.mention} set build version to {version}."
        )
        await main.update_status_message()


class LoadBackupView(View):
    def __init__(self):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
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
            f"♻️ {interaction.user.mention} restored backup `{self.selected}`."
        )


class RemoveFileView(View):
    def __init__(self):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
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
            f"🗑 {interaction.user.mention} deleted `{self.category}/{item_rel_base}`."
        )


class ArchiveReviewView(View):
    def __init__(self, archived_path: str):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.archived_path = archived_path

        keep_btn = Button(
            label="\U0001F4E6 Flag & Keep Archived", style=ButtonStyle.secondary
        )
        keep_btn.callback = self.keep
        self.add_item(keep_btn)

        del_btn = Button(
            label="\u274c Delete Corrupted File(s)", style=ButtonStyle.danger
        )
        del_btn.callback = self.delete
        self.add_item(del_btn)

        noop_btn = Button(
            label="\U0001F552 Acknowledge / Defer", style=ButtonStyle.secondary
        )
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
        await main.log_action(f"🗑 {interaction.user.mention} deleted archived `{self.archived_path}`.")
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
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
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
            f"\U0001F5C2 {interaction.user.mention} archived `{self.category}/{item_rel_base}`."
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
                    timestamp = datetime.now(UTC).strftime("%H:%M UTC")
                    msg = (
                        "\U0001F5C2\uFE0F Archive Action: File Archived\n"
                        "─────────────────────────────\n"
                        f"Operator: {interaction.user.mention} \n"
                        f"File: {self.category}/{item_rel_base}  \n"
                        "Action: Archived (moved to cold storage)  \n"
                        f"Timestamp: {timestamp}\n"
                        f"Ping: {mention}\n\n"
                        "Note: Archived files can be restored or purged at any time by Lead Archivist authority."
                    )
                    await channel.send(msg, view=view)
                except Exception:
                    pass


class ViewArchivedFilesView(View):
    def __init__(self):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.category = None
        sel = Select(
            placeholder="Step 1: Select archived category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_archived_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="arch_view_cat_v1",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_archived_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Archived Files",
                    description=f"Category: **{self.category}**\n(No archived files found)",
                    color=0x888888,
                ),
                view=self,
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="arch_view_item_v1",
        )
        sel_item.callback = self.view_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Archived Files",
                description=f"Category: **{self.category}**\nSelect an item…",
                color=0x888888,
            ),
            view=self,
        )

    async def view_item(self, interaction: nextcord.Interaction):
        item_rel_base = interaction.data["values"][0]
        found = _find_existing_item_key(f"_archived/{self.category}", item_rel_base)
        if not found:
            return await interaction.response.send_message(
                "❌ File not found.", ephemeral=True
            )
        key, _ext = found
        try:
            data = read_json(key)
            blob = json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            try:
                blob = read_text(key)
            except Exception:
                return await interaction.response.send_message(
                    "❌ Could not read file.", ephemeral=True
                )
        show = blob if len(blob) <= 1800 else blob[:1800] + "\n…(truncated)"
        embed = Embed(
            title=f"{item_rel_base} — Archived",
            description=f"```txt\n{show}\n```" if show else "",
            color=0x888888,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class RestoreArchivedFileView(View):
    def __init__(self):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.category = None
        sel = Select(
            placeholder="Step 1: Select archived category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_archived_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="arch_restore_cat_v1",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_archived_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Restore Archived File",
                    description=f"Category: **{self.category}**\n(No archived files found)",
                    color=0x888888,
                ),
                view=self,
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="arch_restore_item_v1",
        )
        sel_item.callback = self.restore_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Restore Archived File",
                description=f"Category: **{self.category}**\nSelect an item…",
                color=0x888888,
            ),
            view=self,
        )

    async def restore_item(self, interaction: nextcord.Interaction):
        item_rel_base = interaction.data["values"][0]
        try:
            restored_path = restore_archived_file(self.category, item_rel_base)
        except FileNotFoundError:
            return await interaction.response.send_message(
                "❌ File not found.", ephemeral=True
            )
        await interaction.response.send_message(
            f"📂 Restored `{self.category}/{item_rel_base}`.", ephemeral=True
        )
        import main
        await main.log_action(
            f"📂 {interaction.user.mention} restored `{self.category}/{item_rel_base}` from archive."
        )

class GrantClearanceView(View):
    def __init__(self):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
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
                f"🟩 {inter2.user.mention} granted {self.roles_to_add} on `{self.category}/{self.item}`."
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
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
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
                f"🟥 {inter2.user.mention} revoked {self.roles_to_remove} on `{self.category}/{self.item}`."
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
            max_length=CONTENT_MAX_LENGTH,
            default=existing_content[:CONTENT_MAX_LENGTH],
        )
        self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            if self.parent_view.limit_edits:
                now = datetime.now(UTC)
                history = [
                    t for t in _EDIT_LOG[self.parent_view.user.id] if now - t < timedelta(hours=1)
                ]
                if len(history) >= 6:
                    return await interaction.response.send_message(
                        "❌ Edit limit reached (6 per hour).", ephemeral=True
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
                f"✏️ {interaction.user.mention} edited RAW `{self.parent_view.category}/{self.parent_view.item}`."
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
        self.value = TextInput(label="New value", style=TextInputStyle.paragraph, min_length=1, max_length=CONTENT_MAX_LENGTH)
        self.add_item(self.field)
        self.add_item(self.value)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            if self.parent_view.limit_edits:
                now = datetime.now(UTC)
                history = [
                    t for t in _EDIT_LOG[self.parent_view.user.id] if now - t < timedelta(hours=1)
                ]
                if len(history) >= 6:
                    return await interaction.response.send_message(
                        "❌ Edit limit reached (6 per hour).", ephemeral=True
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
                f"🛠 {interaction.user.mention} patched `{self.field.value.strip()}` on `{self.parent_view.category}/{self.parent_view.item}`."
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
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
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

        if not self.limit_edits:
            btn_patch = Button(
                label="🛠 Patch JSON Field",
                style=ButtonStyle.success,
                custom_id="patch_field_v1",
            )

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
        if not self.limit_edits:
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
            interaction.user.id,
            comment,
        )
        import main

        await main.log_action(
            f"🖊️ {interaction.user.mention} annotated `{self.parent_view.category}/{self.parent_view.item}`: {comment}"
        )
        await interaction.response.send_message(
            f"✅ Added comment for `{self.parent_view.category}/{self.parent_view.item}`.",
            ephemeral=True,
        )


class EditAnnotationModal(Modal):
    def __init__(self, parent_view: "AnnotateFileView", index: int, existing: str):
        super().__init__(title="Edit Comment")
        self.parent_view = parent_view
        self.index = index
        self.note = TextInput(
            label="Comment",
            style=TextInputStyle.paragraph,
            max_length=400,
            default=existing,
        )
        self.add_item(self.note)

    async def callback(self, interaction: nextcord.Interaction):
        comment = self.note.value.strip()
        if not comment:
            return await interaction.response.send_message(
                "❌ Comment cannot be empty.", ephemeral=True
            )
        try:
            update_file_annotation(
                self.parent_view.category,
                self.parent_view.item,
                self.index,
                comment,
                interaction.user.id,
            )
        except PermissionError:
            return await interaction.response.send_message(
                "❌ You can only edit your own notes.", ephemeral=True
            )
        import main

        await main.log_action(
            f"🖊️ {interaction.user.mention} edited `{self.parent_view.category}/{self.parent_view.item}` note #{self.index + 1}: {comment}"
        )
        await interaction.response.send_message("✅ Note updated.", ephemeral=True)


class AnnotateFileView(View):
    def __init__(self, user: nextcord.Member):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
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
        self.clear_items()
        action = Select(
            placeholder="Choose action…",
            options=[
                SelectOption(label="Add note", value="add"),
                SelectOption(label="Edit note", value="edit"),
                SelectOption(label="Remove note", value="remove"),
            ],
            min_values=1,
            max_values=1,
            custom_id="annotate_action_v1",
        )
        action.callback = self.choose_action
        self.add_item(action)

        notes = list_file_annotations(self.category, self.item)
        summary = "\n".join(notes) if notes else "_No notes yet._"
        if len(summary) > 1000:
            summary = summary[-1000:]
        await interaction.response.edit_message(
            embed=Embed(
                title="Annotate File",
                description=(
                    f"Category: **{self.category}**\\n"
                    f"Item: **{self.item}**\\n"
                    "Choose an action…\\n\\nCurrent notes:\n"
                    f"{summary}"
                ),
                color=0x00FFCC,
            ),
            view=self,
        )

    async def choose_action(self, interaction: nextcord.Interaction):
        act = interaction.data["values"][0]
        if act == "add":
            return await interaction.response.send_modal(AnnotateModal(self))
        if act == "edit":
            return await self.open_edit(interaction)
        if act == "remove":
            return await self.open_delete(interaction)

    async def open_edit(self, interaction: nextcord.Interaction):
        notes = list_file_annotations(self.category, self.item)
        if not notes:
            return await interaction.response.send_message(
                "❌ No notes to edit.", ephemeral=True
            )
        opts = [
            SelectOption(label=f"{i + 1}: {n[:95]}", value=str(i))
            for i, n in enumerate(notes[:25])
        ]
        sel = Select(
            placeholder="Select note to edit…",
            options=opts,
            min_values=1,
            max_values=1,
            custom_id="annotate_edit_v1",
        )

        async def _on_select(inter2: nextcord.Interaction):
            idx = int(inter2.data["values"][0])
            existing = notes[idx].split(":", 1)[-1].strip()
            await inter2.response.send_modal(
                EditAnnotationModal(self, idx, existing)
            )

        sel.callback = _on_select
        self.clear_items()
        self.add_item(sel)
        await interaction.response.edit_message(
            embed=Embed(
                title="Edit Note", description="Select note to edit…", color=0x00FFCC
            ),
            view=self,
        )

    async def open_delete(self, interaction: nextcord.Interaction):
        notes = list_file_annotations(self.category, self.item)
        if not notes:
            return await interaction.response.send_message(
                "❌ No notes to delete.", ephemeral=True
            )
        opts = [
            SelectOption(label=f"{i + 1}: {n[:95]}", value=str(i))
            for i, n in enumerate(notes[:25])
        ]
        sel = Select(
            placeholder="Select note to remove…",
            options=opts,
            min_values=1,
            max_values=1,
            custom_id="annotate_del_v1",
        )

        async def _on_select(inter2: nextcord.Interaction):
            idx = int(inter2.data["values"][0])
            try:
                remove_file_annotation(
                    self.category,
                    self.item,
                    idx,
                    _removal_author_id(inter2.user),
                )
            except PermissionError:
                await inter2.response.send_message(
                    "❌ You can only remove your own notes.", ephemeral=True
                )
            else:
                await inter2.response.send_message(
                    "🗑️ Note removed.", ephemeral=True
                )

        sel.callback = _on_select
        self.clear_items()
        self.add_item(sel)
        await interaction.response.edit_message(
            embed=Embed(
                title="Remove Note",
                description="Select note to remove…",
                color=0xFF5555,
            ),
            view=self,
        )


class ReplyModal(Modal):
    def __init__(self, case_url: str):
        super().__init__(title="Reply to Case")
        self.case_url = case_url
        self.details = TextInput(label="Details", style=TextInputStyle.paragraph)
        self.add_item(self.details)

    async def callback(self, interaction: nextcord.Interaction):
        channel = interaction.client.get_channel(REPORT_REPLY_CHANNEL_ID)
        if not channel:
            try:
                channel = await interaction.client.fetch_channel(
                    REPORT_REPLY_CHANNEL_ID
                )
            except Exception:
                channel = None
        message = (
            f"📝 {interaction.user.mention} replied {self.case_url}: {self.details.value}"
        )
        if channel:
            await channel.send(message)
        await interaction.response.send_message("Reply sent.", ephemeral=True)


class ReportReplyActionsView(View):
    def __init__(self, case_url: str):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.case_url = case_url
        ack = Button(label="Acknowledge", style=ButtonStyle.success)
        ack.callback = self.acknowledge
        reply = Button(label="Reply", style=ButtonStyle.secondary)
        reply.callback = self.open_reply
        snooze = Button(label="Snooze 1h", style=ButtonStyle.secondary)
        snooze.callback = self.snooze
        mute = Button(label="Mute Case", style=ButtonStyle.secondary)
        mute.callback = self.mute
        self.add_item(ack)
        self.add_item(reply)
        self.add_item(snooze)
        self.add_item(mute)

    async def acknowledge(self, interaction: nextcord.Interaction):
        channel = interaction.client.get_channel(REPORT_REPLY_CHANNEL_ID)
        if not channel:
            try:
                channel = await interaction.client.fetch_channel(
                    REPORT_REPLY_CHANNEL_ID
                )
            except Exception:
                channel = None
        message = f"📗 {interaction.user.mention} acknowledged {self.case_url}"
        if channel:
            await channel.send(message)
        embed = interaction.message.embeds[0].copy() if interaction.message.embeds else None
        if embed:
            embed.color = 0x22C55E
            embed.title = embed.title.replace("[INFO]", "[ACK]")
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("Acknowledged.", ephemeral=True)

    async def open_reply(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(ReplyModal(self.case_url))

    async def snooze(self, interaction: nextcord.Interaction):
        await interaction.response.send_message("Snoozed for 1h.", ephemeral=True)

    async def mute(self, interaction: nextcord.Interaction):
        await interaction.response.send_message("Case muted.", ephemeral=True)


class ReportProblemReplyModal(Modal):
    def __init__(self, reporter_id: int, title: str, case_url: str):
        super().__init__(title="Send Signal")
        self.reporter_id = reporter_id
        self.title = title
        self.case_url = case_url
        self.summary = TextInput(
            label="Summary",
            placeholder="One-line summary",
            style=TextInputStyle.short,
            max_length=200,
        )
        self.actions = TextInput(
            label="Actions",
            placeholder="Action 1\nAction 2\nAction 3",
            style=TextInputStyle.paragraph,
            required=False,
            max_length=200,
        )
        self.add_item(self.summary)
        self.add_item(self.actions)

    async def callback(self, interaction: nextcord.Interaction):
        user = interaction.client.get_user(self.reporter_id)
        if not user:
            try:
                user = await interaction.client.fetch_user(self.reporter_id)
            except Exception:
                user = None
        if not user:
            return await interaction.response.send_message(
                "❌ Reporter not found.", ephemeral=True
            )
        try:
            timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
            channel_name = getattr(interaction.channel, "name", "direct-message")
            summary = self.summary.value.replace("\n", " ")
            actions = [
                line.strip()
                for line in self.actions.value.splitlines()
                if line.strip()
            ][:3]
            status = "INFO"
            color = 0x3B82F6
            embed = Embed(
                title=f"Lead Archivist Signal — 🧭 {self.title} [{status}]",
                description=f"Summary: {summary}",
                color=color,
            )
            embed.add_field(
                name="📌 Origin",
                value=f"{interaction.user.mention} in #{channel_name} • 🕒 {timestamp}",
                inline=False,
            )
            if actions:
                embed.add_field(
                    name="✅ Actions",
                    value="\n".join(f"• {a}" for a in actions),
                    inline=False,
                )
            embed.set_footer(text="Archive Control • Reply age: 0m")
            await user.send(embed=embed, view=ReportReplyActionsView(self.case_url))
            await interaction.response.send_message(
                "✅ Signal sent to reporter in DM.", ephemeral=True
            )
            import main

            await main.log_action(
                f"📨 {interaction.user.mention} signaled report '{self.title}' for <@{self.reporter_id}>: {summary}"
            )
        except Exception:
            await interaction.response.send_message(
                "❌ Could not send DM to reporter.", ephemeral=True
            )


class ReportProblemView(View):
    def __init__(self, reporter_id: int, title: str):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.reporter_id = reporter_id
        self.title = title
        btn = Button(label="Reply", style=ButtonStyle.primary)
        btn.callback = self.open_reply
        self.add_item(btn)

    async def open_reply(self, interaction: nextcord.Interaction):
        if not _is_lead_archivist(interaction.user):
            return await interaction.response.send_message(
                "⛔ Lead Archivist only.", ephemeral=True
            )
        await interaction.response.send_modal(
            ReportProblemReplyModal(
                self.reporter_id, self.title, interaction.message.jump_url
            )
        )


class ReportProblemModal(Modal):
    def __init__(self, user: nextcord.Member):
        super().__init__(title="Report Problem")
        self.user = user
        self.title_input = TextInput(
            label="Title",
            placeholder="Short summary",
            min_length=1,
            max_length=200,
        )
        self.description = TextInput(
            label="Description",
            placeholder="Describe the issue and affected file",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=CONTENT_MAX_LENGTH,
        )
        self.add_item(self.title_input)
        self.add_item(self.description)

    async def callback(self, interaction: nextcord.Interaction):
        title = self.title_input.value.strip()
        note = self.description.value.strip()
        channel = None
        if REPORT_REPLY_CHANNEL_ID:
            channel = interaction.guild.get_channel(REPORT_REPLY_CHANNEL_ID)
            if not channel:
                try:
                    channel = await interaction.client.fetch_channel(
                        REPORT_REPLY_CHANNEL_ID
                    )
                except Exception:
                    channel = None
        mention = (
            f"<@&{LEAD_ARCHIVIST_ROLE_ID}>" if LEAD_ARCHIVIST_ROLE_ID else "Lead Archivists"
        )
        if channel:
            try:
                timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
                msg = (
                    "\U0001F6A8 Archivist Incident Report\n"
                    "─────────────────────────────\n"
                    f"Reporter: {interaction.user.mention} \n"
                    f"Category: {title} \n"
                    f"Timestamp: {timestamp}\n"
                    f"Details: \"{note}\"\n"
                    f"PING: {mention}"
                )
                await channel.send(
                    msg, view=ReportProblemView(interaction.user.id, title)
                )
            except Exception:
                pass
        await interaction.response.send_message(
            "\U0001F6A8 Archivist incident report submitted.", ephemeral=True
        )
        import main
        await main.log_action(
            f"\U0001F6A8 {interaction.user.mention} filed ARCHIVIST incident '{title}': {note}"
        )


class ArchivistConsoleView(View):
    """One-stop console for archivists; ephemeral."""

    def __init__(self, user: nextcord.Member):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
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

        self.btn_archived = Button(label="🕸 Archived Files", style=ButtonStyle.secondary)
        self.btn_archived.callback = self.open_archived
        self.add_item(self.btn_archived)

        self.btn_restore = Button(label="📂 Restore File", style=ButtonStyle.secondary)
        self.btn_restore.callback = self.open_restore
        self.add_item(self.btn_restore)

        self.btn_activity = Button(label="🕑 Recent Activity", style=ButtonStyle.secondary)
        self.btn_activity.callback = self.open_recent
        self.add_item(self.btn_activity)

        self.btn_summon = Button(label="📣 Summon Menus", style=ButtonStyle.secondary)
        self.btn_summon.callback = self.summon_menus
        self.add_item(self.btn_summon)

    async def open_upload(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Upload File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=UploadFileView(),
            ephemeral=True,
        )

    async def open_remove(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Remove File",
                description="Step 1: Select category…",
                color=0xFF5555,
            ),
            view=RemoveFileView(),
            ephemeral=True,
        )

    async def open_grant(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Grant Clearance",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=GrantClearanceView(),
            ephemeral=True,
        )

    async def open_revoke(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Revoke Clearance",
                description="Step 1: Select category…",
                color=0xFF0000,
            ),
            view=RevokeClearanceView(),
            ephemeral=True,
        )

    async def open_edit(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Edit File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=EditFileView(self.user),
            ephemeral=True,
        )

    async def open_annotate(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Annotate File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=AnnotateFileView(self.user),
            ephemeral=True,
        )

    async def open_build(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(BuildVersionModal())

    async def open_backup(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Load Backup",
                description="Select backup to restore…",
                color=0x00FFCC,
            ),
            view=LoadBackupView(),
            ephemeral=True,
        )

    async def open_archived(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Archived Files",
                description="Select archived category…",
                color=0x888888,
            ),
            view=ViewArchivedFilesView(),
            ephemeral=True,
        )

    async def open_restore(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Restore Archived File",
                description="Select archived category…",
                color=0x888888,
            ),
            view=RestoreArchivedFileView(),
            ephemeral=True,
        )

    async def open_recent(self, interaction: nextcord.Interaction):
        import main
        try:
            raw = main.read_text("logs/actions.log").splitlines()
            allowed = main.RECENT_ACTION_KEYWORDS
            logs = [
                l
                for l in raw
                if l[:4].isdigit()
                and any(k in l for k in allowed)
                and "trainee submission" not in l
            ]
        except Exception:
            logs = []
        recent = "\n".join(
            reversed([main._format_recent_action(l) for l in logs[-10:]])
        )
        embed = Embed(
            title="Recent Activity",
            description=recent or "(no activity)",
            color=0x3C2E7D,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def summon_menus(self, interaction: nextcord.Interaction):
        await _summon_menus(interaction)


class ArchivistLimitedConsoleView(View):
    """Limited console for regular archivists; ephemeral."""

    def __init__(self, user: nextcord.Member):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
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

        self.btn_request = Button(label="🚩 Report Problem", style=ButtonStyle.secondary)
        self.btn_request.callback = self.open_report_problem
        self.add_item(self.btn_request)

        self.btn_summon = Button(label="📣 Summon Menus", style=ButtonStyle.secondary)
        self.btn_summon.callback = self.summon_menus
        self.add_item(self.btn_summon)

    async def open_upload(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Upload File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=UploadFileView(BASIC_ASSIGN_ROLES),
            ephemeral=True,
        )

    async def open_archive(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Archive File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=ArchiveFileView(),
            ephemeral=True,
        )

    async def open_edit(self, interaction: nextcord.Interaction):
        user_roles = {r.id for r in interaction.user.roles}
        has_archivist = (
            ARCHIVIST_ROLE_ID in user_roles
            or LEAD_ARCHIVIST_ROLE_ID in user_roles
            or interaction.user.guild_permissions.administrator
            or interaction.user.id == interaction.guild.owner_id
        )
        now = time.time()
        user_id = interaction.user.id
        if has_archivist and now - _last_edit_verified.get(user_id, 0) < 600:
            await interaction.response.send_message(
                embed=Embed(
                    title="Edit File",
                    description="Step 1: Select category…",
                    color=0x00FFCC,
                ),
                view=EditFileView(interaction.user, limit_edits=True),
                ephemeral=True,
            )
            return
        try:
            if has_archivist:
                _last_edit_verified[user_id] = now
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send(
                embed=Embed(
                    title="🛰️ Running security clearance protocols…",
                    description=(
                        "Authenticating operator ID against Glacier Unit-7 mainframe.\n"
                        "Stand by for system response."
                    ),
                    color=0x00FFCC,
                ),
                ephemeral=True,
            )

            await asyncio.sleep(3)

            await msg.edit(
                embed=Embed(
                    title="[ACCESS NODE: ONLINE]",
                    description=(
                        "> Uplink established to GU7 Command Systems\n"
                        "> Initiating clearance verification sequence…\n"
                        "> Scanning operator credentials...\n"
                        "> Decrypting authorization codes…\n"
                        "> Cross-referencing classified databases..."
                    ),
                    color=0x00FFCC,
                )
            )

            await asyncio.sleep(random.randint(2, 3))

            if has_archivist:
                await msg.edit(
                    embed=Embed(
                        description=(
                            "> CREDENTIALS VERIFIED\n"
                            "> Access Level: [CLASSIFIED]\n"
                            "> Secure editor interface unlocked. Redirecting…"
                        ),
                        color=0x00FFCC,
                    ),
                    view=EditFileView(interaction.user, limit_edits=True),
                )
                _last_edit_verified[user_id] = time.time()
            else:
                await msg.edit(
                    embed=Embed(
                        description=(
                            "> ACCESS OVERRIDE FAILED\n"
                            "> Operator clearance level insufficient.\n"
                            "> All attempts have been logged by GU7 Security Command."
                        ),
                        color=0xFF5555,
                    ),
                    view=None,
                )
                _last_edit_verified.pop(user_id, None)
        except Exception as e:
            import main
            await main.log_action(
                f"❗ open_edit error: {e}\n```{traceback.format_exc()[:1800]}```"
            )
            if has_archivist:
                _last_edit_verified.pop(user_id, None)
            try:
                await interaction.followup.send(
                    "❌ Could not open editor (see log).", ephemeral=True
                )
            except Exception:
                pass

    async def open_annotate(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Annotate File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=AnnotateFileView(self.user),
            ephemeral=True,
        )

    async def open_report_problem(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(ReportProblemModal(self.user))

    async def summon_menus(self, interaction: nextcord.Interaction):
        await _summon_menus(interaction)


class TraineeSubmissionReviewView(View):
    def __init__(self, user_id: int, sub_id: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.sub_id = sub_id
        self.message: nextcord.Message | None = None

        approve = Button(label="Approve", style=ButtonStyle.success)
        approve.callback = self.approve
        self.add_item(approve)

        request_changes = Button(label="Request Changes", style=ButtonStyle.secondary)
        request_changes.callback = self.request_changes
        self.add_item(request_changes)

        deny = Button(label="Deny", style=ButtonStyle.danger)
        deny.callback = self.deny
        self.add_item(deny)

    async def _check_role(self, interaction: nextcord.Interaction) -> bool:
        if LEAD_ARCHIVIST_ROLE_ID and LEAD_ARCHIVIST_ROLE_ID not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message("⛔ Lead Archivist only.", ephemeral=True)
            return False
        return True

    async def approve(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        data = _load_submission(self.user_id, self.sub_id)
        action = data.get("action", {})
        try:
            if action.get("type") == "upload":
                key = create_dossier_file(action["category"], action["item"], action.get("content", ""), prefer_txt_default=True)
                role_id = action.get("role_id")
                if role_id:
                    grant_file_clearance(action["category"], _strip_ext(action["item"]), role_id)
            elif action.get("type") == "edit":
                update_dossier_raw(action["category"], _strip_ext(action["item"]), action.get("content", ""))
            elif action.get("type") == "archive":
                archive_dossier_file(action["category"], _strip_ext(action["item"]))
            elif action.get("type") == "annotate":
                add_file_annotation(
                    action["category"],
                    _strip_ext(action["item"]),
                    self.user_id,
                    action.get("content", ""),
                )
            _complete_submission(self.user_id, self.sub_id, "approved")
            await interaction.response.send_message("✅ Submission approved.", ephemeral=True)
            import main
            await main.log_action(f"✅ {interaction.user.mention} approved trainee submission {self.sub_id}.")
        except Exception as e:
            import main, traceback
            await main.log_action(f"❗ trainee approve error: {e}\n```{traceback.format_exc()[:1800]}```")
            await interaction.response.send_message("❌ Failed to apply action (see log).", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    async def request_changes(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        await interaction.response.send_modal(TraineeSubmissionRequestChangesModal(self))

    async def deny(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        self.message = interaction.message
        await interaction.response.send_modal(TraineeSubmissionDenyModal(self))


class TraineeSubmissionDenyModal(Modal):
    def __init__(self, parent_view: TraineeSubmissionReviewView):
        super().__init__(title="Deny Submission")
        self.parent_view = parent_view
        self.reason = TextInput(
            label="Reason",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=1000,
        )
        self.add_item(self.reason)

    async def callback(self, interaction: nextcord.Interaction):
        if not await self.parent_view._check_role(interaction):
            return
        reason = self.reason.value.strip()
        data = _load_submission(self.parent_view.user_id, self.parent_view.sub_id)
        action = data.get("action", {})
        _complete_submission(self.parent_view.user_id, self.parent_view.sub_id, "denied", reason)
        user = interaction.guild.get_member(self.parent_view.user_id)
        if not user:
            try:
                user = await interaction.client.fetch_user(self.parent_view.user_id)
            except Exception:
                user = None
        if user:
            try:
                file = None
                content = action.get("content")
                if content:
                    filename = os.path.basename(action.get("item", "submission.txt"))
                    file = nextcord.File(
                        io.BytesIO(content.encode("utf-8")), filename=filename
                    )
                await user.send(
                    f"❌ Your submission {self.parent_view.sub_id} was denied.\nReason: {reason}",
                    file=file,
                )
            except Exception:
                pass
        await interaction.response.send_message("Submission denied.", ephemeral=True)
        import main
        await main.log_action(
            f"❌ {interaction.user.mention} denied trainee submission {self.parent_view.sub_id}: {reason}"
        )
        for child in self.parent_view.children:
            child.disabled = True
        if self.parent_view.message:
            await self.parent_view.message.edit(view=self.parent_view)


class TraineeSubmissionRequestChangesModal(Modal):
    def __init__(self, parent_view: TraineeSubmissionReviewView):
        super().__init__(title="Request Changes")
        self.parent_view = parent_view
        self.reason = TextInput(
            label="Reason",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=1000,
        )
        self.add_item(self.reason)

    async def callback(self, interaction: nextcord.Interaction):
        if not await self.parent_view._check_role(interaction):
            return
        reason = self.reason.value.strip()
        data = _load_submission(self.parent_view.user_id, self.parent_view.sub_id)
        data["reason"] = reason
        save_json(
            _submission_key(self.parent_view.user_id, "pending", self.parent_view.sub_id),
            data,
        )
        action = data.get("action", {})
        user = interaction.guild.get_member(self.parent_view.user_id)
        if not user:
            try:
                user = await interaction.client.fetch_user(self.parent_view.user_id)
            except Exception:
                user = None
        if user:
            try:
                file = None
                content = action.get("content")
                if content:
                    filename = os.path.basename(action.get("item", "submission.txt"))
                    file = nextcord.File(
                        io.BytesIO(content.encode("utf-8")), filename=filename
                    )
                await user.send(
                    f"📝 Changes requested for your submission {self.parent_view.sub_id}.\nReason: {reason}",
                    file=file,
                )
            except Exception:
                pass
        await interaction.response.send_message("Changes requested.", ephemeral=True)
        import main
        await main.log_action(
            f"📝 {interaction.user.mention} requested changes for trainee submission {self.parent_view.sub_id}: {reason}"
        )


async def _notify_leads(interaction: nextcord.Interaction, sub_id: str, action: dict) -> None:
    if not LEAD_NOTIFICATION_CHANNEL_ID:
        return
    channel = interaction.guild.get_channel(LEAD_NOTIFICATION_CHANNEL_ID)
    if not channel:
        try:
            channel = await interaction.client.fetch_channel(LEAD_NOTIFICATION_CHANNEL_ID)
        except Exception:
            channel = None
    if channel:
        desc = (
            f"{interaction.user.mention} submitted `{action.get('type')}` for "
            f"`{action.get('category')}/{action.get('item')}`."
        )
        embed = Embed(title="Trainee Submission", description=desc, color=0x00FFCC)
        view = TraineeSubmissionReviewView(interaction.user.id, sub_id)
        try:
            await channel.send(embed=embed, view=view)
        except Exception:
            pass


class TraineeUploadDetailsModal(Modal):
    def __init__(
        self,
        parent_view: "TraineeUploadFileView",
        item_rel: str | None = None,
        pages: list[str] | None = None,
        page: int = 1,
    ):
        super().__init__(title="Trainee Upload")
        self.parent_view = parent_view
        self.item_rel = item_rel
        self.pages = pages or []
        self.page = page

        if self.item_rel is None:
            self.item = TextInput(label="File path", min_length=1, max_length=4000)
            self.add_item(self.item)

        self.content = TextInput(
            label=f"Content (page {self.page})",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=CONTENT_MAX_LENGTH,
        )
        self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        if self.item_rel is None:
            self.item_rel = self.item.value.strip()

        self.pages.append(self.content.value)

        await interaction.response.send_message(
            "Page saved. Add another page or submit for review.",
            view=TraineeUploadMoreView(self),
            ephemeral=True,
        )


class TraineeUploadMoreView(View):
    """Prompt for trainees to continue upload across multiple pages."""

    def __init__(self, modal: TraineeUploadDetailsModal):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.modal = modal

        btn_more = Button(label="Add Page", style=ButtonStyle.secondary)
        btn_more.callback = self.add_page
        self.add_item(btn_more)

        btn_finish = Button(label="Submit", style=ButtonStyle.success)
        btn_finish.callback = self.finish
        self.add_item(btn_finish)

    async def add_page(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(
            TraineeUploadDetailsModal(
                self.modal.parent_view,
                self.modal.item_rel,
                self.modal.pages,
                self.modal.page + 1,
            )
        )

    async def finish(self, interaction: nextcord.Interaction):
        action = {
            "type": "upload",
            "category": self.modal.parent_view.category,
            "item": self.modal.item_rel,
            "content": "".join(self.modal.pages),
            "role_id": self.modal.parent_view.role_id,
        }
        sub_id = _save_submission(interaction.user.id, action)
        await interaction.response.send_message(
            "📝 Submission pending lead review.", ephemeral=True
        )
        await _notify_leads(interaction, sub_id, action)


class TraineeUploadFileView(View):
    def __init__(self):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.category: str | None = None
        self.role_id: int | None = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="trainee_upload_cat",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        roles = [r for r in interaction.guild.roles if r.id in ALLOWED_ASSIGN_ROLES]
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
            custom_id="trainee_upload_role",
        )

        async def choose_role(inter2: nextcord.Interaction):
            self.role_id = int(inter2.data["values"][0])
            await inter2.response.send_message("Role selected.", ephemeral=True)

        sel_role.callback = choose_role
        self.add_item(sel_role)

        confirm = Button(label="Submit Upload…", style=ButtonStyle.success)

        async def open_modal(inter2: nextcord.Interaction):
            await inter2.response.send_modal(TraineeUploadDetailsModal(self))

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


class TraineeEditContentModal(Modal):
    def __init__(self, parent_view: "TraineeEditFileView", existing: str):
        super().__init__(title="Trainee Edit")
        self.parent_view = parent_view
        self.content = TextInput(
            label="New Content",
            style=TextInputStyle.paragraph,
            default_value=existing[:CONTENT_MAX_LENGTH],
            min_length=1,
            max_length=CONTENT_MAX_LENGTH,
        )
        self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        action = {
            "type": "edit",
            "category": self.parent_view.category,
            "item": self.parent_view.item,
            "content": self.content.value,
        }
        sub_id = _save_submission(interaction.user.id, action)
        await interaction.response.send_message(
            "📝 Submission pending lead review.", ephemeral=True
        )
        await _notify_leads(interaction, sub_id, action)


class TraineeEditFileView(View):
    def __init__(self):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.category: str | None = None
        self.item: str | None = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="trainee_edit_cat",
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
            custom_id="trainee_edit_item",
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
        embed = Embed(title="Edit File", color=0x00FFCC)
        embed.add_field(
            name="File", value=f"`{self.category}/{self.item}{ext}`", inline=False
        )
        embed.add_field(
            name="Preview",
            value=(
                f"```json\n{short}\n```" if ext == ".json" else f"```txt\n{short}\n```"
            ),
            inline=False,
        )
        btn = Button(label="Submit Edit…", style=ButtonStyle.primary)

        async def open_modal(inter2: nextcord.Interaction):
            await inter2.response.send_modal(TraineeEditContentModal(self, preview))

        btn.callback = open_modal
        back = Button(label="← Back", style=ButtonStyle.secondary)

        async def go_back(inter2: nextcord.Interaction):
            await self.__init__()
            await inter2.response.edit_message(
                embed=Embed(
                    title="Edit File",
                    description="Step 1: Select category…",
                    color=0x00FFCC,
                ),
                view=self,
            )

        back.callback = go_back
        self.add_item(btn)
        self.add_item(back)
        await interaction.response.edit_message(embed=embed, view=self)


class TraineeArchiveFileView(View):
    def __init__(self):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.category: str | None = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="trainee_archive_cat",
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
            custom_id="trainee_archive_item",
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
        action = {
            "type": "archive",
            "category": self.category,
            "item": item_rel_base,
        }
        sub_id = _save_submission(interaction.user.id, action)
        await interaction.response.send_message(
            "📝 Submission pending lead review.", ephemeral=True
        )
        await _notify_leads(interaction, sub_id, action)


class TraineeAnnotateModal(Modal):
    def __init__(self, parent_view: "TraineeAnnotateFileView"):
        super().__init__(title="Trainee Annotation")
        self.parent_view = parent_view
        self.note = TextInput(
            label="Comment", style=TextInputStyle.paragraph, max_length=400
        )
        self.add_item(self.note)

    async def callback(self, interaction: nextcord.Interaction):
        action = {
            "type": "annotate",
            "category": self.parent_view.category,
            "item": self.parent_view.item,
            "content": self.note.value,
        }
        sub_id = _save_submission(interaction.user.id, action)
        await interaction.response.send_message(
            "📝 Submission pending lead review.", ephemeral=True
        )
        await _notify_leads(interaction, sub_id, action)


class TraineeAnnotateFileView(View):
    def __init__(self):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.category: str | None = None
        self.item: str | None = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1,
            custom_id="trainee_annotate_cat",
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
            custom_id="trainee_annotate_item",
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
        await interaction.response.send_modal(TraineeAnnotateModal(self))


class TraineeTaskSelectView(View):
    def __init__(self, user: nextcord.Member):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.user = user

        btn_u = Button(label="📂 Upload File", style=ButtonStyle.primary)
        btn_u.callback = self.open_upload
        self.add_item(btn_u)

        btn_e = Button(label="✏️ Edit File", style=ButtonStyle.secondary)
        btn_e.callback = self.open_edit
        self.add_item(btn_e)

        btn_a = Button(label="🗄️ Archive File", style=ButtonStyle.secondary)
        btn_a.callback = self.open_archive
        self.add_item(btn_a)

        btn_n = Button(label="🔍 Annotate File", style=ButtonStyle.secondary)
        btn_n.callback = self.open_annotate
        self.add_item(btn_n)

    async def open_upload(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Upload File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=TraineeUploadFileView(),
            ephemeral=True,
        )

    async def open_edit(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Edit File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=TraineeEditFileView(),
            ephemeral=True,
        )

    async def open_archive(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Archive File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=TraineeArchiveFileView(),
            ephemeral=True,
        )

    async def open_annotate(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Annotate File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=TraineeAnnotateFileView(),
            ephemeral=True,
        )


class ArchivistTraineeConsoleView(View):
    """Console for Archivist trainees; actions require approval."""

    def __init__(self, user: nextcord.Member):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.user = user

        btn_start = Button(label="🧪 Start Task", style=ButtonStyle.primary)
        btn_start.callback = self.open_start
        self.add_item(btn_start)

        btn_pending = Button(label="📦 Pending Submissions", style=ButtonStyle.secondary)
        btn_pending.callback = self.open_pending
        self.add_item(btn_pending)

        btn_completed = Button(label="📜 Completed Tasks", style=ButtonStyle.secondary)
        btn_completed.callback = self.open_completed
        self.add_item(btn_completed)

        btn_help = Button(label="❓ Help", style=ButtonStyle.secondary)
        btn_help.callback = self.open_help
        self.add_item(btn_help)

    async def open_start(self, interaction: nextcord.Interaction):
        text = (
            "[ACCESS NODE: TASK CONSOLE]\n"
            "> Initializing task parameters…\n"
            f"> Operator verified: {interaction.user.mention}\n"
            "> Training node: SANDBOX MODE ACTIVE\n"
            "─────────────────────────────────────\n"
            "SELECT TASK TYPE\n\n"
            "Choose an operation to simulate in the training sandbox.\n"
            "Actions remain *Pending* until reviewed by a Lead-Archivist.\n"
            "─────────────────────────────────────\n"
            "[📂 Upload File] [✏️ Edit File] [🗄️ Archive File]\n"
            "[🔍 Annotate File] \n"
            "─────────────────────────────────────"
        )
        await interaction.response.send_message(
            text, view=TraineeTaskSelectView(self.user), ephemeral=True
        )

    async def open_pending(self, interaction: nextcord.Interaction):
        subs = _list_submissions(interaction.user.id, "pending")
        desc = "\n".join(
            f"`{s['id']}` {s['action'].get('type')} {s['action'].get('category')}/{s['action'].get('item')}"
            for s in subs
        ) or "(none)"
        embed = Embed(title="Pending Submissions", description=desc, color=0x00FFCC)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def open_completed(self, interaction: nextcord.Interaction):
        subs = _list_submissions(interaction.user.id, "completed")
        desc = "\n".join(
            f"`{s['id']}` {s['status']} {s['action'].get('type')} {s['action'].get('category')}/{s['action'].get('item')}"
            for s in subs
        ) or "(none)"
        embed = Embed(title="Completed Tasks", description=desc, color=0x00FFCC)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def open_help(self, interaction: nextcord.Interaction):
        embed = Embed(
            title="Help",
            description=(
                "Use Start Task to propose uploads, edits or archives. "
                "Submissions require Lead approval."
            ),
            color=0x00FFCC,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


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
                f"⬆️ {message.author.mention} uploaded `{category}/{item_rel_input}` → `{key}`."
            )
            processed = True

    if not processed:
        await message.channel.send("❌ No .json/.txt files found in the upload.")
