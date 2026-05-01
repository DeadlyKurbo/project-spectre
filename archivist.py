import json
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, UTC
import asyncio
import random
import time
import io
from uuid import uuid4
from typing import Sequence

import nextcord
from nextcord import Embed, SelectOption, ButtonStyle, TextInputStyle
from nextcord.abc import GuildChannel
from nextcord.ui import View, Select, Button, Modal, TextInput
from async_utils import run_blocking

from constants import (
    UPLOAD_CHANNEL_ID,
    ARCHIVIST_ROLE_ID,
    LEAD_ARCHIVIST_ROLE_ID,
    HIGH_COMMAND_ROLE_ID,
    LEVEL1_ROLE_ID,
    LEVEL2_ROLE_ID,
    LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID,
    LEVEL5_ROLE_ID,
    CLASSIFIED_ROLE_ID,
    LEAD_NOTIFICATION_CHANNEL_ID,
    REPORT_REPLY_CHANNEL_ID,
    ARCHIVIST_MENU_TIMEOUT,
    INTRO_TITLE,
    INTRO_DESC,
    TRAINEE_ROLE_ID,
    TRAINEE_ARCHIVIST_TITLE,
    TRAINEE_ARCHIVIST_DESC,
    CONTENT_MAX_LENGTH,
    PAGE_SEPARATOR,
    ROOT_PREFIX,
    CATEGORY_ORDER,
    CATEGORY_STYLES,
    ARCHIVE_COLOR,
    ARCHIVE_FOOTER_UPLOAD,
    ARCHIVE_FOOTER_CLEARANCE,
    MENU_CHANNEL_ID,
)
from server_config import (
    get_assignable_roles,
    get_clearance_levels,
    get_roles_for_level,
    get_server_config,
    invalidate_config,
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
    move_dossier_file,
    rename_category,
    delete_category,
    reorder_categories,
    update_category_style,
    update_dossier_raw,
    patch_dossier_json_field,
    attach_dossier_image,
    _find_existing_item_key,
    _strip_ext,
    read_json,
    read_text,
)
from acl import (
    grant_file_clearance,
    grant_level_clearance,
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

from views import RootView
from utils import get_category_label, iter_category_styles
from operator_login import detect_clearance, list_operators, update_id_code, delete_operator


# ======== Archivist helpers ========


CLEARANCE_NAME_FALLBACKS = {
    1: "Confidential",
    2: "Restricted",
    3: "Secret",
    4: "Ultra",
    5: "Omega",
    6: "Classified",
}

FORMATTED_UPLOAD_FIELDS = (
    "file_type",
    "subject",
    "status",
    "clearance",
    "last_update",
    "file_link",
)
FORMATTED_UPLOAD_TEMPLATE = json.dumps(
    {field: "" for field in FORMATTED_UPLOAD_FIELDS},
    ensure_ascii=False,
    indent=2,
)


def _assignable_role_ids(guild_id: int | None = None) -> list[int]:
    """Return the configured set of roles allowed for clearance actions."""

    roles = get_assignable_roles(guild_id)
    if roles:
        return roles
    # Preserve historical behaviour using the constant fallback when the
    # dashboard has not been configured yet.
    fallback = [
        LEVEL1_ROLE_ID,
        LEVEL2_ROLE_ID,
        LEVEL3_ROLE_ID,
        LEVEL4_ROLE_ID,
        LEVEL5_ROLE_ID,
        CLASSIFIED_ROLE_ID,
    ]
    return [rid for rid in fallback if isinstance(rid, int) and rid > 0]


def _formatted_upload_validation_error(content: str) -> str | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return " Formatted upload must be valid JSON."
    if not isinstance(payload, dict):
        return " Formatted upload must be a JSON object."
    missing = [field for field in FORMATTED_UPLOAD_FIELDS if field not in payload]
    if missing:
        return " Formatted upload is missing: " + ", ".join(f"`{field}`" for field in missing)
    return None

_EDIT_LOG: dict[int, list[datetime]] = defaultdict(list)
_last_edit_verified: dict[int, float] = {}

_ARCHIVE_LOCKED_BY_GUILD: dict[int, bool] = {}

_MENU_ANCHOR_PREFIX = "system/archive_menu_anchors"


def _menu_anchor_path(guild_id: int) -> str:
    return f"{_MENU_ANCHOR_PREFIX}/{int(guild_id)}.json"


def _load_menu_anchor(guild_id: int) -> dict[str, int] | None:
    try:
        payload = ss_read_json(_menu_anchor_path(guild_id))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    channel_id = _coerce_channel_id(payload.get("channel_id"))
    message_id = _coerce_channel_id(payload.get("message_id"))
    if channel_id is None:
        return None
    data: dict[str, int] = {"channel_id": channel_id}
    if message_id is not None:
        data["message_id"] = message_id
    return data


def _save_menu_anchor(guild_id: int, channel_id: int, message_id: int) -> None:
    save_json(
        _menu_anchor_path(guild_id),
        {
            "guild_id": int(guild_id),
            "channel_id": int(channel_id),
            "message_id": int(message_id),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def is_archive_locked(guild_id: int | None = None) -> bool:
    """Return True if the archive is locked for this guild. Per-guild, not global."""
    if guild_id is None:
        return False
    return _ARCHIVE_LOCKED_BY_GUILD.get(int(guild_id), False)


def lock_archive(guild_id: int) -> None:
    _ARCHIVE_LOCKED_BY_GUILD[int(guild_id)] = True


def unlock_archive(guild_id: int) -> None:
    _ARCHIVE_LOCKED_BY_GUILD.pop(int(guild_id), None)


def toggle_archive_lock(guild_id: int) -> bool:
    gid = int(guild_id)
    current = _ARCHIVE_LOCKED_BY_GUILD.get(gid, False)
    _ARCHIVE_LOCKED_BY_GUILD[gid] = not current
    return _ARCHIVE_LOCKED_BY_GUILD[gid]


def _categories_for_select(limit: int = 25, guild_id: int | None = None) -> list[str]:
    """Return up to ``limit`` dossier categories for UI selects."""

    try:
        return list_categories(guild_id=guild_id)[:limit]
    except TypeError:
        return list_categories()[:limit]


def _archived_categories_for_select(limit: int = 25, guild_id: int | None = None) -> list[str]:
    """Return up to ``limit`` archived dossier categories for UI selects."""

    try:
        return list_archived_categories(guild_id=guild_id)[:limit]
    except TypeError:
        return list_archived_categories()[:limit]

# ===== Personnel file links =====
_PERSONNEL_LINKS: dict[int | None, dict[int, list[str]]] = {}


def _guild_root_prefix(guild_id: int | None = None) -> str:
    base = ROOT_PREFIX
    if guild_id is not None:
        try:
            cfg = get_server_config(guild_id)
        except Exception:
            cfg = None
        if hasattr(cfg, "get"):
            base = cfg.get("ROOT_PREFIX", ROOT_PREFIX)
    if not isinstance(base, str):
        return ""
    return base.strip().strip("/")


def _personnel_links_file(guild_id: int | None = None) -> str:
    prefix = _guild_root_prefix(guild_id)
    if prefix:
        return f"{prefix}/personnel_links.json"
    return "personnel_links.json"


def _load_personnel_links(guild_id: int | None = None) -> dict[int, list[str]]:
    cache_key = int(guild_id) if guild_id is not None else None
    cached = _PERSONNEL_LINKS.get(cache_key)
    if cached is not None:
        return cached
    try:
        raw = ss_read_json(_personnel_links_file(guild_id))
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    parsed = {int(k): list(v) for k, v in raw.items()}
    _PERSONNEL_LINKS[cache_key] = parsed
    return parsed


def link_personnel_file(user_id: int, file_key: str, guild_id: int | None = None) -> None:
    links_map = _load_personnel_links(guild_id)
    links = links_map.setdefault(int(user_id), [])
    if file_key not in links:
        links.append(file_key)
    save_json(
        _personnel_links_file(guild_id),
        {str(k): v for k, v in links_map.items()},
    )


def get_personnel_files(user_id: int, guild_id: int | None = None) -> list[str]:
    links_map = _load_personnel_links(guild_id)
    files = list(links_map.get(int(user_id), []))
    try:
        found = _find_existing_item_key("personnel", str(user_id), guild_id=guild_id)
        if found:
            path, _ext = found
            files.insert(0, path)
    except Exception:
        pass
    return files

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


def _role_ids(member: nextcord.abc.User | nextcord.Member) -> set[int]:
    """Return a set of role IDs for ``member`` while tolerating missing attrs."""

    raw_roles = getattr(member, "roles", None) or []
    role_ids: set[int] = set()
    for role in raw_roles:
        role_id = getattr(role, "id", None)
        if role_id is None:
            continue
        try:
            role_ids.add(int(role_id))
        except (TypeError, ValueError):
            continue
    return role_ids


def _is_owner_or_admin(user: nextcord.Member) -> bool:
    """Return True if ``user`` is the guild owner or has administrator perms."""

    guild = getattr(user, "guild", None)
    owner_id = getattr(guild, "owner_id", None)
    user_id = getattr(user, "id", None)
    if owner_id is not None and user_id is not None and owner_id == user_id:
        return True
    permissions = getattr(user, "guild_permissions", None)
    return bool(getattr(permissions, "administrator", False))


def _has_configured_role(role_id: int, user_roles: set[int]) -> bool:
    """Return ``True`` when ``role_id`` is set and present in ``user_roles``."""

    return bool(role_id) and role_id in user_roles


def _coerce_int(value: object) -> int | None:
    """Return value as int when possible."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip(), 10)
    except (TypeError, ValueError):
        return None


def _archivist_role_ids(guild_id: int | None) -> tuple[int, int, int, int]:
    """Return (archivist, lead_archivist, high_command, trainee) role IDs for the guild.

    Uses dashboard config when available; falls back to constants for DMs or missing config.
    """
    if guild_id is not None:
        cfg = get_server_config(guild_id)
        if isinstance(cfg, dict):
            arch = _coerce_int(cfg.get("ARCHIVIST_ROLE_ID")) or ARCHIVIST_ROLE_ID
            lead = _coerce_int(cfg.get("LEAD_ARCHIVIST_ROLE_ID")) or LEAD_ARCHIVIST_ROLE_ID
            high = _coerce_int(cfg.get("HIGH_COMMAND_ROLE_ID")) or HIGH_COMMAND_ROLE_ID
            trainee = _coerce_int(cfg.get("TRAINEE_ROLE_ID")) or TRAINEE_ROLE_ID
            return (arch or 0, lead or 0, high or 0, trainee or 0)
    return (
        ARCHIVIST_ROLE_ID or 0,
        LEAD_ARCHIVIST_ROLE_ID or 0,
        HIGH_COMMAND_ROLE_ID or 0,
        TRAINEE_ROLE_ID or 0,
    )


def _is_archivist(user: nextcord.Member, guild_id: int | None = None) -> bool:
    guild_id = guild_id or (getattr(getattr(user, "guild", None), "id", None))
    user_roles = _role_ids(user)
    arch_id, lead_id, high_id, trainee_id = _archivist_role_ids(guild_id)
    return (
        _is_owner_or_admin(user)
        or _has_configured_role(arch_id, user_roles)
        or _has_configured_role(lead_id, user_roles)
        or _has_configured_role(high_id, user_roles)
        or _has_configured_role(trainee_id, user_roles)
    )


def _is_lead_archivist(user: nextcord.Member, guild_id: int | None = None) -> bool:
    guild_id = guild_id or (getattr(getattr(user, "guild", None), "id", None))
    user_roles = _role_ids(user)
    _arch_id, lead_id, high_id, _trainee_id = _archivist_role_ids(guild_id)
    return (
        _is_owner_or_admin(user)
        or _has_configured_role(lead_id, user_roles)
        or _has_configured_role(high_id, user_roles)
    )


def _is_high_command(user: nextcord.Member, guild_id: int | None = None) -> bool:
    guild_id = guild_id or (getattr(getattr(user, "guild", None), "id", None))
    user_roles = _role_ids(user)
    _arch_id, _lead_id, high_id, _trainee_id = _archivist_role_ids(guild_id)
    return (
        _is_owner_or_admin(user)
        or _has_configured_role(high_id, user_roles)
    )


def _removal_author_id(user: nextcord.Member) -> int | None:
    """Return author ID to enforce annotation removal permissions.

    Lead archivists may remove any note, so return ``None`` to disable the
    author check. Regular archivists must provide their own user ID.
    """
    return None if _is_lead_archivist(user) else user.id


def _coerce_channel_id(value: object) -> int | None:
    """Return ``value`` normalised as a channel identifier when possible."""

    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, GuildChannel):
        return value.id
    try:
        as_str = str(value).strip()
    except Exception:
        return None
    if not as_str:
        return None
    try:
        return int(as_str, 10)
    except ValueError:
        return None


def extract_menu_channel_id(config: object) -> int | None:
    """Resolve the configured menu channel identifier from ``config``."""

    getter = getattr(config, "get", None)

    def _get(key: str, default: object = None) -> object:
        if callable(getter):
            try:
                return getter(key, default)  # type: ignore[misc]
            except TypeError:
                return getter(key)  # type: ignore[call-arg]
        if isinstance(config, dict):
            return config.get(key, default)  # type: ignore[assignment]
        return getattr(config, key, default)

    for candidate in (
        _get("MENU_CHANNEL_ID"),
        _get("menu_channel_id"),  # defensive legacy casing
    ):
        coerced = _coerce_channel_id(candidate)
        if coerced is not None:
            return coerced

    channels = _get("channels")
    if isinstance(channels, dict):
        coerced = _coerce_channel_id(channels.get("menu_home"))
        if coerced is not None:
            return coerced

    settings = _get("settings")
    if isinstance(settings, dict):
        coerced = _coerce_channel_id(settings.get("MENU_CHANNEL_ID"))
        if coerced is not None:
            return coerced
        channels = settings.get("channels")
        if isinstance(channels, dict):
            coerced = _coerce_channel_id(channels.get("menu_home"))
            if coerced is not None:
                return coerced

    return None


async def refresh_menus(
    guild: nextcord.Guild, menu_channel_override: int | None = None
) -> None:
    """Deploy a fresh archive menu for ``guild``.

    The previous menu message is always removed before a new one is sent,
    ensuring operators see a fresh, non-stale interaction surface after
    process restarts and manual redeploys.

    ``menu_channel_override`` allows callers (such as manual dashboard
    deployments) to force a specific delivery channel when the cached
    configuration is stale.
    """

    invalidate_config(guild.id)
    cfg = get_server_config(guild.id)

    # Ensure the persistent root view is registered for this guild before
    # sending the menu.  Dashboard-driven deployments may occur before the
    # view has been added via ``on_ready``, which would cause component
    # interactions to fail with "Interaction failed" in Discord.
    try:
        guild._state._get_client().add_view(RootView(guild.id))
    except Exception:
        pass

    stored_anchor = _load_menu_anchor(guild.id)

    preferred_ids: list[int] = []
    for candidate in (
        menu_channel_override,
        stored_anchor.get("channel_id") if isinstance(stored_anchor, dict) else None,
        extract_menu_channel_id(cfg),
        _coerce_channel_id(MENU_CHANNEL_ID),
    ):
        coerced = _coerce_channel_id(candidate)
        if coerced is not None and coerced not in preferred_ids:
            preferred_ids.append(coerced)
    if not preferred_ids:
        return

    get_channel_or_thread = getattr(guild, "get_channel_or_thread", None)
    menu_ch = None
    for menu_channel_id in preferred_ids:
        if callable(get_channel_or_thread):
            menu_ch = get_channel_or_thread(menu_channel_id)
        else:
            menu_ch = guild.get_channel(menu_channel_id)
        if menu_ch and hasattr(menu_ch, "send"):
            break
    else:
        return

    title = cfg.get("INTRO_TITLE", INTRO_TITLE)
    desc = cfg.get("INTRO_DESC", INTRO_DESC)
    color = cfg.get("ARCHIVE_COLOR", ARCHIVE_COLOR)
    embed = Embed(title=title, description=desc, color=color)
    footer = cfg.get("ROOT_FOOTER")
    if footer:
        embed.set_footer(text=footer)
    thumb = cfg.get("ROOT_THUMBNAIL")
    if thumb:
        embed.set_thumbnail(url=thumb)

    async def _delete_message(message: object) -> bool:
        delete = getattr(message, "delete", None)
        if not callable(delete):
            return False
        try:
            await delete()
            return True
        except Exception:
            return False

    # Remove the previously anchored menu first so a redeploy always creates
    # a fresh interaction surface instead of editing existing components.
    old_message_id = None
    if isinstance(stored_anchor, dict):
        old_message_id = _coerce_channel_id(stored_anchor.get("message_id"))
    if old_message_id is not None:
        try:
            old_message = await menu_ch.fetch_message(old_message_id)
        except Exception:
            old_message = None
        if old_message is not None:
            await _delete_message(old_message)

    # Clean up stale bot-authored archive menu messages that may survive
    # process restarts (for example when an older message was never anchored).
    try:
        bot_user_id = guild._state._get_client().user.id
    except Exception:
        bot_user_id = None
    history = getattr(menu_ch, "history", None)
    if callable(history) and bot_user_id is not None:
        try:
            async for message in history(limit=30):
                if getattr(getattr(message, "author", None), "id", None) != bot_user_id:
                    continue
                if old_message_id is not None and getattr(message, "id", None) == old_message_id:
                    continue
                components = getattr(message, "components", None) or []
                embeds = getattr(message, "embeds", None) or []
                has_components = bool(components)
                has_archive_embed = any(
                    getattr(embed, "title", "") == title for embed in embeds
                )
                if has_components or has_archive_embed:
                    await _delete_message(message)
        except Exception:
            pass

    try:
        sent = await menu_ch.send(embed=embed, view=RootView(guild.id))
        _save_menu_anchor(guild.id, menu_ch.id, sent.id)
    except Exception:
        pass

    

async def _summon_menus(interaction: nextcord.Interaction) -> None:
    """Refresh the menu channel with the latest view."""
    import main

    await refresh_menus(interaction.guild)

    await interaction.response.send_message(" Menus summoned.", ephemeral=True)
    gid = interaction.guild.id if interaction.guild else None
    await main.log_action(
        f" {interaction.user.mention} summoned all menus.",
        guild_id=gid,
    )


class UploadDetailsModal(Modal):
    def __init__(
        self,
        parent_view: "UploadFileView",
        item_rel: str | None = None,
        pages: list[str] | None = None,
        page: int = 1,
    ):
        self.formatted = bool(getattr(parent_view, "formatted", False))
        super().__init__(title="Formatted Archive Upload" if self.formatted else "Archive Upload")
        self.parent_view = parent_view
        self.item_rel = item_rel
        self.pages = pages or []
        self.page = page

        if self.item_rel is None:
            self.item = TextInput(
                label="File path",
                placeholder="e.g. intel/hoot alliance (ext optional)",
                min_length=1,
                max_length=4000,
            )
            self.add_item(self.item)

        content_input_kwargs = {
            "label": "Formatted JSON" if self.formatted else f"Content (page {self.page})",
            "placeholder": "Fill in the JSON file card" if self.formatted else "Paste JSON or plain text",
            "style": TextInputStyle.paragraph,
            "min_length": 1,
            "max_length": CONTENT_MAX_LENGTH,
        }
        if self.formatted and self.page == 1:
            content_input_kwargs["default_value"] = FORMATTED_UPLOAD_TEMPLATE
        self.content = TextInput(**content_input_kwargs)
        self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            role_id = getattr(self.parent_view, "role_id", None)
            if role_id is None:
                return await interaction.response.send_message(
                    " Select a clearance role first.", ephemeral=True
                )

            if self.item_rel is None:
                # Preserve spaces and original casing in the provided path
                # instead of slugging them to underscores.
                self.item_rel = self.item.value.strip().strip("/")

            self.pages.append(self.content.value)

            await interaction.response.send_message(
                "Formatted file saved. Finish the upload."
                if self.formatted
                else "Page saved. Add another page or finish the upload.",
                view=UploadMoreView(self),
                ephemeral=True,
            )
        except FileExistsError:
            await interaction.response.send_message(" File already exists.", ephemeral=True)
        except Exception as e:
            import main
            gid = getattr(self.modal.parent_view, "guild_id", None) or (interaction.guild.id if interaction.guild else None)
            await main.log_action(
                f" Upload modal error: {e}\n```{traceback.format_exc()[:1800]}```",
                guild_id=gid,
            )
            try:
                await interaction.response.send_message(
                    " Upload failed (see log).", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    " Upload failed (see log).", ephemeral=True
                )


class UploadMoreView(View):
    """Prompt to continue upload across multiple pages."""

    def __init__(self, modal: UploadDetailsModal):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.modal = modal

        if not self.modal.formatted:
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
            content = PAGE_SEPARATOR.join(self.modal.pages)
            if self.modal.formatted:
                validation_error = _formatted_upload_validation_error(content)
                if validation_error:
                    return await interaction.response.send_message(
                        validation_error,
                        ephemeral=True,
                    )
            gid = getattr(self.modal.parent_view, "guild_id", None)
            try:
                key = create_dossier_file(
                    self.modal.parent_view.category,
                    self.modal.item_rel,
                    content,
                    prefer_txt_default=not self.modal.formatted,
                    guild_id=gid,
                )
            except TypeError:
                key = create_dossier_file(
                    self.modal.parent_view.category,
                    self.modal.item_rel,
                    content,
                    prefer_txt_default=not self.modal.formatted,
                )
            item_base = _strip_ext(self.modal.item_rel)
            gid = getattr(self.modal.parent_view, "guild_id", None) or (
                interaction.guild.id if interaction.guild else None
            )
            grant_file_clearance(self.modal.parent_view.category, item_base, role_id, guild_id=gid)
            await interaction.response.send_message(
                f" Uploaded `{self.modal.parent_view.category}/{self.modal.item_rel}` with clearance <@&{role_id}>.",
                ephemeral=True,
            )
            import main

            gid = getattr(self.modal.parent_view, "guild_id", None) or (
                interaction.guild.id if interaction.guild else None
            )
            await main.log_action(
                f" {interaction.user.mention} uploaded `{self.modal.parent_view.category}/{self.modal.item_rel}` with clearance <@&{role_id}>.",
                event_type="file_upload",
                clearance=detect_clearance(interaction.user),
                guild_id=gid,
            )
        except FileExistsError:
            await interaction.response.send_message(" File already exists.", ephemeral=True)
        except Exception as e:
            import main
            gid = getattr(self.modal.parent_view, "guild_id", None) or (interaction.guild.id if interaction.guild else None)
            await main.log_action(
                f" Upload modal error: {e}\n```{traceback.format_exc()[:1800]}```",
                guild_id=gid,
            )
            try:
                await interaction.response.send_message(
                    " Upload failed (see log).", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    " Upload failed (see log).", ephemeral=True
                )


class UploadFileView(View):
    def __init__(
        self,
        allowed_roles: Sequence[int] | None = None,
        guild_id: int | None = None,
        formatted: bool = False,
    ):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.formatted = formatted
        self.category = None
        self.role_id = None
        # Preserve provided order to control privilege hierarchy
        if allowed_roles:
            self.allowed_roles = list(allowed_roles)
        else:
            self.allowed_roles = _assignable_role_ids(self.guild_id)
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
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
        roles.sort(key=lambda r: self.allowed_roles.index(r.id))
        if not roles:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Upload Formatted File" if self.formatted else "Upload File",
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

        confirm = Button(
            label="Upload Formatted File" if self.formatted else "Upload...",
            style=ButtonStyle.success,
            custom_id="upload_formatted_go_v1" if self.formatted else "upload_go_v3",
        )

        async def open_modal(inter2: nextcord.Interaction):
            try:
                await inter2.response.send_modal(UploadDetailsModal(self))
            except Exception as e:
                import main
                gid = self.guild_id or (inter2.guild.id if inter2.guild else None)
                await main.log_action(
                    f" open_modal error: {e}\n```{traceback.format_exc()[:1800]}```",
                    guild_id=gid,
                )
                try:
                    await inter2.response.send_message(
                        " Could not open modal (see log).", ephemeral=True
                    )
                except Exception:
                    await inter2.followup.send(
                        " Could not open modal (see log).", ephemeral=True
                    )
        confirm.callback = open_modal
        self.add_item(confirm)

        await interaction.response.edit_message(
            embed=Embed(
                title="Upload Formatted File" if self.formatted else "Upload File",
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
            f" Build version set to {version}.", ephemeral=True
        )
        import main
        gid = interaction.guild.id if interaction.guild else None
        await main.log_action(
            f" {interaction.user.mention} set build version to {version}.",
            guild_id=gid,
        )


def _format_backup_label(filename: str) -> str:
    """Convert backup filename to human-readable label (e.g. 'Gamma • Jan 11, 2025, 11:50 PM')."""
    import re
    match = re.match(r"Backup protocol (\w+)-(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})\.json", filename)
    if match:
        name, y, mo, d, h, mi, s = match.groups()
        try:
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=UTC)
            fmt = dt.strftime("%b %d, %Y, %I:%M %p")
            return f"{name} • {fmt}"
        except (ValueError, TypeError):
            pass
    return filename.replace(".json", "")


class LoadBackupView(View):
    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.selected: str | None = None
        backup_prefix = f"backups/{guild_id or 'global'}"
        try:
            _dirs, files = list_dir(backup_prefix)
        except Exception:
            files = []
        if not files:
            self.add_item(Button(label="No backups found", disabled=True))
            return
        sorted_files = sorted(files, key=lambda x: x[0], reverse=True)
        options = [
            SelectOption(label=_format_backup_label(f), value=f)
            for f, _ in sorted_files
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
        backup_prefix = f"backups/{self.guild_id or 'global'}"
        try:
            _restore_path = f"{backup_prefix}/{self.selected}"
            _restore_backup = getattr(main, "_restore_backup")
            _restore_backup(_restore_path, guild_id=self.guild_id)
        except Exception as e:
            gid = self.guild_id or (interaction.guild.id if interaction.guild else None)
            await main.log_action(
                f" Restore backup error: {e}\n``{traceback.format_exc()[:1800]}``",
                guild_id=gid,
            )
            return await interaction.response.send_message(
                " Restore failed (see log).", ephemeral=True
            )
        await interaction.response.send_message(
            f" Restored `{self.selected}`.", ephemeral=True
        )

        gid = interaction.guild.id if interaction.guild else None
        await main.log_action(
            f" {interaction.user.mention} restored backup `{self.selected}`.",
            event_type="backup_restore",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
        )


class RemoveFileView(View):
    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.category = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
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
        items = list_items_recursive(self.category, guild_id=self.guild_id)
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
            remove_dossier_file(self.category, item_rel_base, guild_id=self.guild_id)
        except FileNotFoundError:
            return await interaction.response.send_message(
                " File not found.", ephemeral=True
            )
        await interaction.response.send_message(
            f" Deleted `{self.category}/{item_rel_base}`.", ephemeral=True
        )
        import main

        gid = self.guild_id or (interaction.guild.id if interaction.guild else None)
        await main.log_action(
            f" {interaction.user.mention} deleted `{self.category}/{item_rel_base}`.",
            event_type="file_delete",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
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
        gid = getattr(interaction.guild, "id", None) if interaction.guild else None
        if not _is_lead_archivist(interaction.user, guild_id=gid):
            await interaction.response.send_message(" Lead Archivist only.", ephemeral=True)
            return False
        return True

    async def keep(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        await interaction.response.send_message(" File kept archived.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    async def delete(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        delete_file(self.archived_path)
        await interaction.response.send_message(" Archived file deleted.", ephemeral=True)
        import main

        gid = interaction.guild.id if interaction.guild else None
        await main.log_action(
            f" {interaction.user.mention} deleted archived `{self.archived_path}`.",
            event_type="file_delete",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
        )
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
    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.category = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
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
        items = list_items_recursive(self.category, guild_id=self.guild_id)
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
            archived_path = archive_dossier_file(
                self.category,
                item_rel_base,
                guild_id=self.guild_id,
            )
        except FileNotFoundError:
            return await interaction.response.send_message(
                " File not found.", ephemeral=True
            )
        await interaction.response.send_message(
            f" Archived `{self.category}/{item_rel_base}`.", ephemeral=True
        )
        import main

        gid = self.guild_id or (interaction.guild.id if interaction.guild else None)
        await main.log_action(
            f"\U0001F5C2 {interaction.user.mention} archived `{self.category}/{item_rel_base}`.",
            event_type="file_delete",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
        )
        gid = interaction.guild.id if interaction.guild else None
        cfg = get_server_config(gid or 0)
        lead_role_id = _coerce_int(cfg.get("LEAD_ARCHIVIST_ROLE_ID")) or LEAD_ARCHIVIST_ROLE_ID
        channel_id = _coerce_int(cfg.get("LEAD_NOTIFICATION_CHANNEL_ID")) or LEAD_NOTIFICATION_CHANNEL_ID
        if channel_id:
            channel = interaction.guild.get_channel(channel_id) if interaction.guild else None
            if not channel and interaction.client:
                try:
                    channel = await interaction.client.fetch_channel(channel_id)
                except Exception:
                    channel = None
            if channel:
                mention = (
                    f"<@&{lead_role_id}>" if lead_role_id else "Lead Archivists"
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


class MoveRenameModal(Modal):
    def __init__(self, parent_view: "MoveFileView"):
        super().__init__(title="Move / Rename File")
        self.parent_view = parent_view
        self.new_name = TextInput(
            label="New file name (without extension)",
            required=False,
            default_value=parent_view.item,
            max_length=200,
        )
        self.add_item(self.new_name)

    async def callback(self, interaction: nextcord.Interaction):
        new_base = self.new_name.value.strip() or self.parent_view.item
        try:
            move_dossier_file(
                self.parent_view.src_category,
                self.parent_view.item,
                self.parent_view.dest_category,
                new_base,
                guild_id=self.parent_view.guild_id,
            )
        except FileNotFoundError:
            return await interaction.response.send_message(
                " File not found.", ephemeral=True
            )
        except FileExistsError:
            return await interaction.response.send_message(
                " Destination already has that name.", ephemeral=True
            )
        await interaction.response.send_message(
            f" Moved `{self.parent_view.src_category}/{self.parent_view.item}` to `"
            f"{self.parent_view.dest_category}/{new_base}`.",
            ephemeral=True,
        )
        import main

        gid = self.parent_view.guild_id or (interaction.guild.id if interaction.guild else None)
        await main.log_action(
            f" {interaction.user.mention} moved `{self.parent_view.src_category}/{self.parent_view.item}` to `"
            f"{self.parent_view.dest_category}/{new_base}`.",
            event_type="archivist_edit",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
        )


class MoveFileView(View):
    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.src_category: str | None = None
        self.item: str | None = None
        self.dest_category: str | None = None
        sel = Select(
            placeholder="Step 1: Select source category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
            ],
            min_values=1,
            max_values=1,
            custom_id="move_src_cat_v1",
        )
        sel.callback = self.select_src_category
        self.add_item(sel)

    async def select_src_category(self, interaction: nextcord.Interaction):
        self.src_category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.src_category, guild_id=self.guild_id)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Move / Rename File",
                    description=f"Category: **{self.src_category}**\\n(No files found)",
                    color=0x00FFCC,
                ),
                view=self,
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="move_item_v1",
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Move / Rename File",
                description=f"Category: **{self.src_category}**\\nSelect an item…",
                color=0x00FFCC,
            ),
            view=self,
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()
        sel_dest = Select(
            placeholder="Step 3: Select destination category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
            ],
            min_values=1,
            max_values=1,
            custom_id="move_dest_cat_v1",
        )
        sel_dest.callback = self.select_dest_category
        self.add_item(sel_dest)
        await interaction.response.edit_message(
            embed=Embed(
                title="Move / Rename File",
                description=f"File: `{self.src_category}/{self.item}`\\nSelect destination category…",
                color=0x00FFCC,
            ),
            view=self,
        )

    async def select_dest_category(self, interaction: nextcord.Interaction):
        self.dest_category = interaction.data["values"][0]
        try:
            await interaction.response.send_modal(MoveRenameModal(self))
        except Exception as e:
            import main

            gid = self.parent_view.guild_id or (interaction.guild.id if interaction.guild else None)
            await main.log_action(
                f" move_rename_modal error: {e}\n```{traceback.format_exc()[:1800]}```",
                guild_id=gid,
            )
            try:
                await interaction.response.send_message(
                    " Could not open modal (see log).", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    " Could not open modal (see log).", ephemeral=True
                )


class ViewArchivedFilesView(View):
    def __init__(self, categories: Sequence[str] | None = None, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.category = None
        opts: list[SelectOption] = []
        cats = (
            categories
            if categories is not None
            else _archived_categories_for_select(guild_id=self.guild_id)
        )
        for slug, label, emoji, _color in iter_category_styles(cats, guild_id=self.guild_id):
            opts.append(SelectOption(label=label, value=slug, emoji=emoji))
        if opts:
            sel = Select(
                placeholder="Step 1: Select archived category…",
                options=opts,
                min_values=1,
                max_values=1,
                custom_id="arch_view_cat_v1",
            )
            sel.callback = self.select_category
            self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_archived_items_recursive(self.category, guild_id=self.guild_id)
        emoji, color = CATEGORY_STYLES.get(self.category, (None, ARCHIVE_COLOR))
        title = get_category_label(self.category, guild_id=self.guild_id)
        if emoji:
            title = f"{emoji} {title}"
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Archived Files",
                    description=f"Category: **{title}**\n(No archived files found)",
                    color=color,
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
                description=f"Category: **{title}**\nSelect an item…",
                color=color,
            ),
            view=self,
        )

    async def view_item(self, interaction: nextcord.Interaction):
        item_rel_base = interaction.data["values"][0]
        found = _find_existing_item_key(
            f"_archived/{self.category}",
            item_rel_base,
            guild_id=self.guild_id,
        )
        if not found:
            return await interaction.response.send_message(
                " File not found.", ephemeral=True
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
                    " Could not read file.", ephemeral=True
                )
        show = blob if len(blob) <= 1800 else blob[:1800] + "\n…(truncated)"
        embed = Embed(
            title=f"{item_rel_base} — Archived",
            description=f"```txt\n{show}\n```" if show else "",
            color=0x888888,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class RestoreArchivedFileView(View):
    def __init__(self, categories: Sequence[str] | None = None, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.category = None
        opts: list[SelectOption] = []
        cats = (
            categories
            if categories is not None
            else _archived_categories_for_select(guild_id=self.guild_id)
        )
        for slug, label, emoji, _color in iter_category_styles(cats, guild_id=self.guild_id):
            opts.append(SelectOption(label=label, value=slug, emoji=emoji))
        if opts:
            sel = Select(
                placeholder="Step 1: Select archived category…",
                options=opts,
                min_values=1,
                max_values=1,
                custom_id="arch_restore_cat_v1",
            )
            sel.callback = self.select_category
            self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_archived_items_recursive(self.category, guild_id=self.guild_id)
        emoji, color = CATEGORY_STYLES.get(self.category, (None, ARCHIVE_COLOR))
        title = get_category_label(self.category, guild_id=self.guild_id)
        if emoji:
            title = f"{emoji} {title}"
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Restore Archived File",
                    description=f"Category: **{title}**\n(No archived files found)",
                    color=color,
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
                description=f"Category: **{title}**\nSelect an item…",
                color=color,
            ),
            view=self,
        )

    async def restore_item(self, interaction: nextcord.Interaction):
        item_rel_base = interaction.data["values"][0]
        try:
            restored_path = restore_archived_file(
                self.category,
                item_rel_base,
                guild_id=self.guild_id,
            )
        except FileNotFoundError:
            return await interaction.response.send_message(
                " File not found.", ephemeral=True
            )
        await interaction.response.send_message(
            f" Restored `{self.category}/{item_rel_base}`.", ephemeral=True
        )
        import main

        gid = self.guild_id or (interaction.guild.id if interaction.guild else None)
        await main.log_action(
            f" {interaction.user.mention} restored `{self.category}/{item_rel_base}` from archive.",
            event_type="file_restore",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
        )

class GrantClearanceView(View):
    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.category = None
        self.item = None
        self.roles_to_add: list[int] = []
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
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
        items = list_items_recursive(self.category, guild_id=self.guild_id)
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

        current = get_required_roles(self.category, self.item, guild_id=self.guild_id)
        allowed_ids = set(_assignable_role_ids(self.guild_id))
        roles = [r for r in interaction.guild.roles if r.id in allowed_ids]
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

        level_map = get_clearance_levels(self.guild_id)
        level_options: list[SelectOption] = []
        for level in range(1, 7):
            configured = get_roles_for_level(level, self.guild_id)
            if not configured:
                continue
            level_name = level_map.get(level, {}).get("name") or CLEARANCE_NAME_FALLBACKS.get(level, f"Level {level}")
            level_options.append(
                SelectOption(label=f"Level {level} • {level_name}", value=str(level))
            )

        if level_options:
            level_select = Select(
                placeholder="Step 4: Apply a clearance level…",
                options=level_options,
                min_values=1,
                max_values=1,
                custom_id="grant_level_v1",
            )

            async def apply_level(inter2: nextcord.Interaction):
                values = inter2.data.get("values") if isinstance(inter2.data, dict) else None
                try:
                    level_choice = int(values[0]) if values else None
                except (TypeError, ValueError):
                    level_choice = None
                if level_choice is None:
                    return await inter2.response.send_message(
                        "Select a valid clearance level first.", ephemeral=True
                    )
                configured_roles = get_roles_for_level(level_choice, self.guild_id)
                if not configured_roles:
                    return await inter2.response.send_message(
                        "No roles are configured for that clearance level.", ephemeral=True
                    )
                added_roles = grant_level_clearance(
                    self.category, self.item, level_choice, guild_id=self.guild_id
                )
                if not added_roles:
                    return await inter2.response.send_message(
                        "All roles for that clearance level already have access.",
                        ephemeral=True,
                    )
                level_label = (
                    level_map.get(level_choice, {}).get("name")
                    or CLEARANCE_NAME_FALLBACKS.get(level_choice, f"Level {level_choice}")
                )
                mentions = ", ".join(f"<@&{rid}>" for rid in added_roles)
                await inter2.response.send_message(
                    f" Granted: {mentions} via {level_label} → `{self.category}/{self.item}`",
                    ephemeral=True,
                )
                import main

                gid = self.guild_id or (inter2.guild.id if inter2.guild else None)
                await main.log_action(
                    f" {inter2.user.mention} granted level {level_choice} roles {added_roles} on `{self.category}/{self.item}`.",
                    event_type="clearance_change",
                    clearance=detect_clearance(inter2.user),
                    guild_id=gid,
                )

            level_select.callback = apply_level
            self.add_item(level_select)

        apply_btn = Button(label="Apply Grants", style=ButtonStyle.success, custom_id="apply_grant_v1")
        async def do_grant(inter2: nextcord.Interaction):
            if not self.roles_to_add:
                return await inter2.response.send_message(
                    "Select at least one role.", ephemeral=True
                )
            for rid in self.roles_to_add:
                grant_file_clearance(self.category, self.item, rid, guild_id=self.guild_id)
            await inter2.response.send_message(
                f" Granted: {', '.join(f'<@&{r}>' for r in self.roles_to_add)} → `{self.category}/{self.item}`",
                ephemeral=True,
            )
            import main

            gid = self.guild_id or (inter2.guild.id if inter2.guild else None)
            await main.log_action(
                f" {inter2.user.mention} granted {self.roles_to_add} on `{self.category}/{self.item}`.",
                event_type="clearance_change",
                clearance=detect_clearance(inter2.user),
                guild_id=gid,
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
    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.category = None
        self.item = None
        self.roles_to_remove: list[int] = []
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
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
        items = list_items_recursive(self.category, guild_id=self.guild_id)
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
                revoke_file_clearance(self.category, self.item, rid, guild_id=self.guild_id)
            await inter2.response.send_message(
                f" Revoked: {', '.join(f'<@&{r}>' for r in self.roles_to_remove)} → `{self.category}/{self.item}`",
                ephemeral=True,
            )
            import main

            gid = self.guild_id or (inter2.guild.id if inter2.guild else None)
            await main.log_action(
                f" {inter2.user.mention} revoked {self.roles_to_remove} on `{self.category}/{self.item}`.",
                event_type="clearance_change",
                clearance=detect_clearance(inter2.user),
                guild_id=gid,
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
        max_len = min(max(len(existing_content), CONTENT_MAX_LENGTH), 4000)
        self.content = TextInput(
            label="Raw content",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=max_len,
            default_value=existing_content[:max_len],
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
                        " Edit limit reached (6 per hour).", ephemeral=True
                    )
                history.append(now)
                _EDIT_LOG[self.parent_view.user.id] = history
            update_dossier_raw(
                self.parent_view.category,
                self.parent_view.item,
                self.content.value,
                guild_id=self.parent_view.guild_id,
            )
            await interaction.response.send_message(
                " File updated.", ephemeral=True
            )
            import main

            gid = self.parent_view.guild_id or (interaction.guild.id if interaction.guild else None)
            await main.log_action(
                f" {interaction.user.mention} edited RAW `{self.parent_view.category}/{self.parent_view.item}`.",
                event_type="archivist_edit",
                clearance=detect_clearance(interaction.user),
                guild_id=gid,
            )
        except Exception as e:
            import main
            gid = self.parent_view.guild_id or (interaction.guild.id if interaction.guild else None)
            await main.log_action(
                f" EditRawModal error: {e}\n```{traceback.format_exc()[:1800]}```",
                guild_id=gid,
            )
            try:
                await interaction.response.send_message(
                    " Update failed (see log).", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    " Update failed (see log).", ephemeral=True
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
                        " Edit limit reached (6 per hour).", ephemeral=True
                    )
                history.append(now)
                _EDIT_LOG[self.parent_view.user.id] = history
            patch_dossier_json_field(
                self.parent_view.category,
                self.parent_view.item,
                self.field.value.strip(),
                self.value.value,
                guild_id=self.parent_view.guild_id,
            )
            await interaction.response.send_message(
                " Field patched.", ephemeral=True
            )
            import main

            gid = self.parent_view.guild_id or (interaction.guild.id if interaction.guild else None)
            await main.log_action(
                f" {interaction.user.mention} patched `{self.field.value.strip()}` on `{self.parent_view.category}/{self.parent_view.item}`.",
                event_type="archivist_edit",
                clearance=detect_clearance(interaction.user),
                guild_id=gid,
            )
        except ValueError as e:
            await interaction.response.send_message(f" {e}", ephemeral=True)
        except Exception as e:
            import main
            gid = self.parent_view.guild_id or (interaction.guild.id if interaction.guild else None)
            await main.log_action(
                f" PatchFieldModal error: {e}\n```{traceback.format_exc()[:1800]}```",
                guild_id=gid,
            )
            try:
                await interaction.response.send_message(
                    " Patch failed (see log).", ephemeral=True
                )
            except Exception:
                await interaction.followup.send(
                    " Patch failed (see log).", ephemeral=True
                )


class EditFileView(View):
    def __init__(
        self,
        user: nextcord.Member,
        limit_edits: bool = False,
        guild_id: int | None = None,
    ):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.user = user
        self.limit_edits = limit_edits
        self.guild_id = guild_id
        self.category = None
        self.item = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
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
        items = list_items_recursive(self.category, guild_id=self.guild_id)
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

        found = _find_existing_item_key(
            self.category,
            self.item,
            guild_id=self.guild_id,
        )
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

        required = get_required_roles(self.category, self.item, guild_id=self.guild_id)
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

        btn_raw = Button(label=" Edit Raw", style=ButtonStyle.primary, custom_id="edit_raw_v1")
        async def open_raw(inter2: nextcord.Interaction):
            try:
                await inter2.response.send_modal(EditRawModal(self, preview))
            except Exception as e:
                import main
                gid = self.guild_id or (inter2.guild.id if inter2.guild else None)
                await main.log_action(
                    f" open_raw error: {e}\n```{traceback.format_exc()[:1800]}```",
                    guild_id=gid,
                )
                try:
                    await inter2.response.send_message(
                        " Could not open modal (see log).", ephemeral=True
                    )
                except Exception:
                    await inter2.followup.send(
                        " Could not open modal (see log).", ephemeral=True
                    )
        btn_raw.callback = open_raw

        if not self.limit_edits:
            btn_patch = Button(
                label=" Patch JSON Field",
                style=ButtonStyle.success,
                custom_id="patch_field_v1",
            )

            async def open_patch(inter2: nextcord.Interaction):
                try:
                    await inter2.response.send_modal(PatchFieldModal(self))
                except Exception as e:
                    import main

                    gid = self.guild_id or (inter2.guild.id if inter2.guild else None)
                    await main.log_action(
                        f" open_patch error: {e}\n```{traceback.format_exc()[:1800]}```",
                        guild_id=gid,
                    )
                    try:
                        await inter2.response.send_message(
                            " Could not open modal (see log).", ephemeral=True
                        )
                    except Exception:
                        await inter2.followup.send(
                            " Could not open modal (see log).", ephemeral=True
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
                " Comment cannot be empty.", ephemeral=True
            )
        add_file_annotation(
            self.parent_view.category,
            self.parent_view.item,
            interaction.user.id,
            comment,
        )
        import main

        gid = self.parent_view.guild_id or (interaction.guild.id if interaction.guild else None)
        await main.log_action(
            f" {interaction.user.mention} annotated `{self.parent_view.category}/{self.parent_view.item}`: {comment}",
            event_type="archivist_edit",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
        )
        await interaction.response.send_message(
            f" Added comment for `{self.parent_view.category}/{self.parent_view.item}`.",
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
                " Comment cannot be empty.", ephemeral=True
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
                " You can only edit your own notes.", ephemeral=True
            )
        import main

        gid = self.parent_view.guild_id or (interaction.guild.id if interaction.guild else None)
        await main.log_action(
            f" {interaction.user.mention} edited `{self.parent_view.category}/{self.parent_view.item}` note #{self.index + 1}: {comment}",
            event_type="archivist_edit",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
        )
        await interaction.response.send_message(" Note updated.", ephemeral=True)


class AnnotateFileView(View):
    def __init__(self, user: nextcord.Member, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.user = user
        self.guild_id = guild_id
        self.category = None
        self.item = None
        try:
            cats = list_categories(guild_id=self.guild_id)
        except TypeError:
            cats = list_categories()
        if not _is_lead_archivist(user):
            cats = [c for c in cats if c != "personnel"]
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in cats
            ],
            min_values=1,
            max_values=1,
            custom_id="annotate_cat_v1",
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        if self.category == "personnel" and not _is_lead_archivist(interaction.user):
            return await interaction.response.send_message(
                " Only lead archivist+ may annotate personnel files.", ephemeral=True
            )
        self.clear_items()
        items = list_items_recursive(self.category, guild_id=self.guild_id)
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
                " No notes to edit.", ephemeral=True
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
                " No notes to delete.", ephemeral=True
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
                    " You can only remove your own notes.", ephemeral=True
                )
            else:
                await inter2.response.send_message(
                    " Note removed.", ephemeral=True
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
    def __init__(self, case_url: str, report_channel_id: int | None = None):
        super().__init__(title="Reply to Case")
        self.case_url = case_url
        self.report_channel_id = report_channel_id
        self.details = TextInput(label="Details", style=TextInputStyle.paragraph)
        self.add_item(self.details)

    async def callback(self, interaction: nextcord.Interaction):
        channel = interaction.client.get_channel(self.report_channel_id or 0)
        if not channel and self.report_channel_id:
            try:
                channel = await interaction.client.fetch_channel(self.report_channel_id)
            except Exception:
                channel = None
        message = (
            f" {interaction.user.mention} replied {self.case_url}: {self.details.value}"
        )
        if channel:
            try:
                await channel.send(message)
            except Exception:
                pass
        await interaction.response.send_message("Reply sent.", ephemeral=True)


class ReportReplyActionsView(View):
    def __init__(self, case_url: str, report_channel_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.case_url = case_url
        self.report_channel_id = report_channel_id
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
        channel = interaction.client.get_channel(self.report_channel_id or 0)
        if not channel and self.report_channel_id:
            try:
                channel = await interaction.client.fetch_channel(self.report_channel_id)
            except Exception:
                channel = None
        message = f" {interaction.user.mention} acknowledged {self.case_url}"
        if channel:
            try:
                await channel.send(message)
            except Exception:
                pass
        embed = interaction.message.embeds[0].copy() if interaction.message.embeds else None
        if embed:
            embed.color = 0x22C55E
            embed.title = embed.title.replace("[INFO]", "[ACK]")
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("Acknowledged.", ephemeral=True)

    async def open_reply(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(
            ReplyModal(self.case_url, report_channel_id=self.report_channel_id)
        )

    async def snooze(self, interaction: nextcord.Interaction):
        await interaction.response.send_message("Snoozed for 1h.", ephemeral=True)

    async def mute(self, interaction: nextcord.Interaction):
        await interaction.response.send_message("Case muted.", ephemeral=True)


class ReportProblemReplyModal(Modal):
    def __init__(
        self,
        reporter_id: int,
        title: str,
        case_url: str,
        report_channel_id: int | None = None,
    ):
        super().__init__(title="Send Signal")
        self.reporter_id = reporter_id
        self.title = title
        self.case_url = case_url
        self.report_channel_id = report_channel_id
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
                " Reporter not found.", ephemeral=True
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
                title=f"Lead Archivist Signal —  {self.title} [{status}]",
                description=f"Summary: {summary}",
                color=color,
            )
            embed.add_field(
                name=" Origin",
                value=f"{interaction.user.mention} in #{channel_name} •  {timestamp}",
                inline=False,
            )
            if actions:
                embed.add_field(
                    name=" Actions",
                    value="\n".join(f"• {a}" for a in actions),
                    inline=False,
                )
            embed.set_footer(text="Archive Control • Reply age: 0m")
            await user.send(
                embed=embed,
                view=ReportReplyActionsView(
                    self.case_url, report_channel_id=self.report_channel_id
                ),
            )
            await interaction.response.send_message(
                " Signal sent to reporter in DM.", ephemeral=True
            )
            import main

            gid = interaction.guild.id if interaction.guild else None
            await main.log_action(
                f" {interaction.user.mention} signaled report '{self.title}' for <@{self.reporter_id}>: {summary}",
                guild_id=gid,
            )
        except Exception:
            await interaction.response.send_message(
                " Could not send DM to reporter.", ephemeral=True
            )


class ReportProblemView(View):
    def __init__(
        self,
        reporter_id: int,
        title: str,
        report_channel_id: int | None = None,
    ):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.reporter_id = reporter_id
        self.title = title
        self.report_channel_id = report_channel_id
        btn = Button(label="Reply", style=ButtonStyle.primary)
        btn.callback = self.open_reply
        self.add_item(btn)

    async def open_reply(self, interaction: nextcord.Interaction):
        if not _is_lead_archivist(interaction.user):
            return await interaction.response.send_message(
                " Lead Archivist only.", ephemeral=True
            )
        await interaction.response.send_modal(
            ReportProblemReplyModal(
                self.reporter_id,
                self.title,
                interaction.message.jump_url,
                report_channel_id=self.report_channel_id,
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
        guild_id = getattr(getattr(interaction, "guild", None), "id", 0)
        cfg = get_server_config(guild_id)
        report_channel_id = _coerce_channel_id(cfg.get("REPORT_REPLY_CHANNEL_ID"))
        lead_role_id = _coerce_channel_id(cfg.get("LEAD_ARCHIVIST_ROLE_ID"))
        channel = None
        guild = getattr(interaction, "guild", None)
        if report_channel_id and guild:
            channel = guild.get_channel(report_channel_id)
            if not channel:
                try:
                    channel = await interaction.client.fetch_channel(report_channel_id)
                except Exception:
                    channel = None
        mention = (
            f"<@&{lead_role_id}>" if lead_role_id else "Lead Archivists"
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
                    msg,
                    view=ReportProblemView(
                        interaction.user.id,
                        title,
                        report_channel_id=report_channel_id,
                    ),
                )
            except Exception:
                pass
        await interaction.response.send_message(
            "\U0001F6A8 Archivist incident report submitted.", ephemeral=True
        )
        import main
        gid = interaction.guild.id if interaction.guild else None
        await main.log_action(
            f"\U0001F6A8 {interaction.user.mention} filed ARCHIVIST incident '{title}': {note}",
            guild_id=gid,
        )


class FileManagementView(View):
    def __init__(self, console: "ArchivistConsoleView"):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.console = console

        buttons = [
            ("Upload File", ButtonStyle.primary, "📤", console.open_upload),
            ("Upload Formatted File", ButtonStyle.success, None, console.open_formatted_upload),
            ("Remove File", ButtonStyle.danger, "🗑️", console.open_remove),
            ("Grant Clearance", ButtonStyle.success, "✅", console.open_grant),
            ("Revoke Clearance", ButtonStyle.danger, "⛔", console.open_revoke),
            ("Edit File", ButtonStyle.secondary, "✏️", console.open_edit),
            ("Move/Rename File", ButtonStyle.secondary, "📁", console.open_move),
            ("Annotate File", ButtonStyle.secondary, "📝", console.open_annotate),
            ("Edit Categories", ButtonStyle.secondary, "🗂️", console.open_categories),
        ]
        for label, style, emoji, callback in buttons:
            btn = Button(label=label, style=style, emoji=emoji)
            btn.callback = callback
            self.add_item(btn)

        if _is_lead_archivist(console.user):
            btn = Button(label="Link Personnel", style=ButtonStyle.secondary, emoji="👤")
            btn.callback = console.open_link_personnel
            self.add_item(btn)


class LinkPersonnelView(View):
    def __init__(self, guild: nextcord.Guild):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild = guild
        self.guild_id = getattr(guild, "id", None)
        self.user_id: int | None = None
        self.category: str | None = None

        op_options: list[SelectOption] = []
        for op in list_operators():
            member = guild.get_member(op.user_id)
            if not member:
                continue
            label = f"{member.display_name} – {op.id_code}"
            op_options.append(SelectOption(label=label[:100], value=str(op.user_id)))

        sel = Select(
            placeholder="Step 1: Select operator…",
            options=op_options,
            min_values=1,
            max_values=1,
            custom_id="link_personnel_op_v1",
        )
        sel.callback = self.select_operator
        self.add_item(sel)

    async def select_operator(self, interaction: nextcord.Interaction):
        self.user_id = int(interaction.data["values"][0])
        self.clear_items()
        sel = Select(
            placeholder="Step 2: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
            ],
            min_values=1,
            max_values=1,
            custom_id="link_personnel_cat_v1",
        )
        sel.callback = self.select_category
        self.add_item(sel)
        await interaction.response.edit_message(
            embed=Embed(
                title="Link File to User",
                description="Step 2: Select category…",
                color=0x00FFCC,
            ),
            view=self,
        )

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category, guild_id=self.guild_id)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(
                    title="Link File to User",
                    description=f"Category: **{self.category}**\\n(No files found)",
                    color=0x00FFCC,
                ),
                view=self,
            )
        sel = Select(
            placeholder="Step 3: Select file…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1,
            max_values=1,
            custom_id="link_personnel_item_v1",
        )
        sel.callback = self.link_file
        self.add_item(sel)
        await interaction.response.edit_message(
            embed=Embed(
                title="Link File to User",
                description=f"Category: **{self.category}**\\nSelect a file…",
                color=0x00FFCC,
            ),
            view=self,
        )

    async def link_file(self, interaction: nextcord.Interaction):
        item = interaction.data["values"][0]
        try:
            link_personnel_file(
                self.user_id,
                f"{self.category}/{item}",
                guild_id=self.guild_id,
            )
            await interaction.response.send_message(" File linked.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(
                f" Link failed: {e}", ephemeral=True
            )


class RenameCategoryModal(Modal):
    def __init__(self, slug: str, label: str, guild_id: int | None = None):
        super().__init__(title="Rename Category")
        self.old_slug = slug
        self.guild_id = guild_id
        self.new = TextInput(label="New Slug", default_value=slug, required=True)
        self.label = TextInput(
            label="New Label", default_value=label, required=False
        )
        self.add_item(self.new)
        self.add_item(self.label)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            rename_category(
                self.old_slug,
                self.new.value,
                self.label.value or None,
                guild_id=self.guild_id,
            )
            await interaction.response.send_message(
                " Category renamed.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f" Rename failed: {e}", ephemeral=True
            )


class RenameCategorySelectView(View):
    def __init__(self, console: "ArchivistConsoleView"):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.console = console
        opts = []
        for slug, label, emoji, _color in iter_category_styles(
            guild_id=console.guild_id
        ):
            opts.append(SelectOption(label=label, value=slug, emoji=emoji))
        sel = Select(placeholder="Select category…", options=opts)
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        slug = interaction.data["values"][0]
        label = get_category_label(slug, guild_id=self.console.guild_id)
        await interaction.response.send_modal(
            RenameCategoryModal(slug, label, guild_id=self.console.guild_id)
        )


class EditCategoryStyleModal(Modal):
    def __init__(self, slug: str):
        super().__init__(title="Edit Category Style")
        self.slug = slug
        current_emoji, current_color = CATEGORY_STYLES.get(slug, (None, ARCHIVE_COLOR))
        self.emoji = TextInput(
            label="Emoji", default_value=current_emoji or "", required=False
        )
        self.color = TextInput(
            label="Color", default_value=f"0x{current_color:06X}", required=False
        )
        self.add_item(self.emoji)
        self.add_item(self.color)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            update_category_style(
                self.slug,
                emoji=self.emoji.value,
                color=self.color.value.strip() or None,
            )
            await interaction.response.send_message(
                " Category style updated.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f" Update failed: {e}", ephemeral=True
            )


class EditCategoryStyleSelectView(View):
    def __init__(self, console: "ArchivistConsoleView"):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.console = console
        opts = []
        for slug, label, emoji, _color in iter_category_styles(
            guild_id=console.guild_id
        ):
            opts.append(SelectOption(label=label, value=slug, emoji=emoji))
        sel = Select(placeholder="Select category…", options=opts)
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        slug = interaction.data["values"][0]
        await interaction.response.send_modal(EditCategoryStyleModal(slug))


class ReorderCategoriesView(View):
    def __init__(self, console: "ArchivistConsoleView"):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.console = console
        self.guild_id = console.guild_id
        self.remaining = [slug for slug, _label in CATEGORY_ORDER]
        self.selected: list[str] = []
        opts = []
        for slug, label, emoji, _color in iter_category_styles(
            self.remaining, guild_id=self.guild_id
        ):
            opts.append(SelectOption(label=label, value=slug, emoji=emoji))
        self.selector = Select(
            placeholder="Select category for position 1…",
            options=opts,
        )
        self.selector.callback = self.pick
        self.add_item(self.selector)

    async def pick(self, interaction: nextcord.Interaction):
        choice = interaction.data["values"][0]
        self.selected.append(choice)
        if choice in self.remaining:
            self.remaining.remove(choice)
        if not self.remaining:
            reorder_categories(self.selected)
            await interaction.response.edit_message(
                content=" Categories reordered.", view=None
            )
            return
        opts = []
        for slug, label, emoji, _color in iter_category_styles(
            self.remaining, guild_id=self.guild_id
        ):
            opts.append(SelectOption(label=label, value=slug, emoji=emoji))
        self.selector.options = opts
        self.selector.placeholder = (
            f"Select category for position {len(self.selected) + 1}…"
        )
        selected_labels = [
            get_category_label(s, guild_id=self.guild_id) for s in self.selected
        ]
        await interaction.response.edit_message(
            content=f"Selected: {', '.join(selected_labels)}", view=self
        )


class CategoryManagementView(View):
    def __init__(self, console: "ArchivistConsoleView"):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.console = console

        btn_rename = Button(label=" Rename Category", style=ButtonStyle.secondary)
        btn_rename.callback = self.open_rename
        self.add_item(btn_rename)

        btn_style = Button(label=" Edit Category Style", style=ButtonStyle.secondary)
        btn_style.callback = self.open_style
        self.add_item(btn_style)

        btn_reorder = Button(label=" Reorder Categories", style=ButtonStyle.secondary)
        btn_reorder.callback = self.open_reorder
        self.add_item(btn_reorder)

        btn_delete = Button(label=" Delete Category", style=ButtonStyle.danger)
        btn_delete.callback = self.open_delete
        self.add_item(btn_delete)

    async def open_rename(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            "Select category to rename:",
            view=RenameCategorySelectView(self.console),
            ephemeral=True,
        )

    async def open_style(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            "Select category to edit:",
            view=EditCategoryStyleSelectView(self.console),
            ephemeral=True,
        )

    async def open_reorder(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            "Select new category order:",
            view=ReorderCategoriesView(self.console),
            ephemeral=True,
        )

    async def open_delete(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            "Select category to delete:",
            view=DeleteCategorySelectView(self.console),
            ephemeral=True,
        )


class DeleteCategorySelectView(View):
    def __init__(self, console: "ArchivistConsoleView"):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.console = console
        opts = []
        for slug, label, emoji, _color in iter_category_styles(
            guild_id=console.guild_id
        ):
            opts.append(SelectOption(label=label, value=slug, emoji=emoji))
        if not opts:
            self.add_item(Button(label="No categories found", disabled=True))
            return
        sel = Select(placeholder="Select category…", options=opts)
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        slug = interaction.data["values"][0]
        label = get_category_label(slug, guild_id=self.console.guild_id)
        item_count = len(list_items_recursive(slug, guild_id=self.console.guild_id))
        archived_count = len(
            list_archived_items_recursive(slug, guild_id=self.console.guild_id)
        )
        total = item_count + archived_count
        await interaction.response.send_message(
            embed=Embed(
                title="Delete Category",
                description=(
                    f"**{label}** (`{slug}`)\n\n"
                    f"This will permanently delete {total} file(s).\n"
                    "This action cannot be undone."
                ),
                color=0xFF0000,
            ),
            view=DeleteCategoryConfirmView(
                self.console, slug, label, total
            ),
            ephemeral=True,
        )


class DeleteCategoryConfirmView(View):
    def __init__(
        self,
        console: "ArchivistConsoleView",
        slug: str,
        label: str,
        file_count: int,
    ):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.console = console
        self.slug = slug
        self.label = label
        self.file_count = file_count

        btn_confirm = Button(label="Delete", style=ButtonStyle.danger, emoji="🗑️")
        btn_confirm.callback = self.confirm
        self.add_item(btn_confirm)

        btn_cancel = Button(label="Cancel", style=ButtonStyle.secondary)
        btn_cancel.callback = self.cancel
        self.add_item(btn_cancel)

    async def confirm(self, interaction: nextcord.Interaction):
        try:
            delete_category(self.slug, guild_id=self.console.guild_id)
            await interaction.response.edit_message(
                content=f" Category **{self.label}** deleted.",
                embed=None,
                view=None,
            )
            import main

            gid = self.console.guild_id or (interaction.guild.id if interaction.guild else None)
            await main.log_action(
                f" {interaction.user.mention} deleted category `{self.slug}` ({self.file_count} file(s)).",
                event_type="category_delete",
                clearance=detect_clearance(interaction.user),
                guild_id=gid,
            )
        except Exception as e:
            await interaction.response.send_message(
                f" Delete failed: {e}",
                ephemeral=True,
            )

    async def cancel(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            content="Delete cancelled.",
            embed=None,
            view=None,
        )


class BotManagementView(View):
    def __init__(self, console: "ArchivistConsoleView"):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.console = console

        buttons = [
            ("Create Backup", ButtonStyle.primary, "💾", console.open_create_backup),
            ("Load Backup", ButtonStyle.secondary, "📦", console.open_backup),
            ("Archived Files", ButtonStyle.secondary, "🗃️", console.open_archived),
            ("Restore File", ButtonStyle.success, "♻️", console.open_restore),
        ]
        for label, style, emoji, callback in buttons:
            btn = Button(label=label, style=style, emoji=emoji)
            btn.callback = callback
            self.add_item(btn)


class EditOperatorIDModal(Modal):
    def __init__(self, user_id: int, current_id: str):
        super().__init__(title="Edit Operator ID")
        self.user_id = user_id
        # ``TextInput`` in nextcord uses ``default_value`` to prefill the
        # field.  Using the older ``default`` parameter raises a ``TypeError``
        # which prevented the modal from opening when the Edit ID button was
        # pressed.  Use the correct keyword so the modal renders properly.
        self.id_input = TextInput(
            label="ID Code", default_value=current_id, max_length=20
        )
        self.add_item(self.id_input)

    async def callback(self, interaction: nextcord.Interaction):
        new_id = self.id_input.value.strip()
        update_id_code(self.user_id, new_id)
        import main

        gid = interaction.guild.id if interaction.guild else None
        await main.log_action(
            f" {interaction.user.mention} updated operator ID for <@{self.user_id}> to `{new_id}`",
            event_type="archivist_edit",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
        )
        await interaction.response.send_message(
            " Operator ID updated.", ephemeral=True
        )


class OperatorIDManagementView(View):
    def __init__(self, operators, guild: nextcord.Guild):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.ops = {op.user_id: op for op in operators}
        self.selected: int | None = None

        options = []
        for op in operators:
            member = guild.get_member(op.user_id)
            name = member.display_name if member else str(op.user_id)
            label = f"{name} – {op.id_code}"
            options.append(SelectOption(label=label[:100], value=str(op.user_id)))

        sel = Select(placeholder="Select operator", options=options, min_values=1, max_values=1)
        sel.callback = self.select_operator
        self.add_item(sel)

        self.edit_btn = Button(label="Edit ID", style=ButtonStyle.primary, disabled=True)
        self.edit_btn.callback = self.edit_id
        self.add_item(self.edit_btn)

        self.del_btn = Button(label="Delete ID", style=ButtonStyle.danger, disabled=True)
        self.del_btn.callback = self.delete_id
        self.add_item(self.del_btn)

    async def select_operator(self, interaction: nextcord.Interaction):
        self.selected = int(interaction.data["values"][0])
        self.edit_btn.disabled = False
        self.del_btn.disabled = False
        await interaction.response.edit_message(view=self)

    async def edit_id(self, interaction: nextcord.Interaction):
        if self.selected is None:
            return
        op = self.ops.get(self.selected)
        if not op:
            return
        await interaction.response.send_modal(
            EditOperatorIDModal(self.selected, op.id_code)
        )

    async def delete_id(self, interaction: nextcord.Interaction):
        if self.selected is None:
            return
        delete_operator(self.selected)
        import main

        gid = interaction.guild.id if interaction.guild else None
        await main.log_action(
            f" {interaction.user.mention} deleted operator ID for <@{self.selected}>",
            event_type="archivist_delete",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
        )
        await interaction.response.send_message(
            " Operator ID deleted.", ephemeral=True
        )


class ArchivistConsoleView(View):
    """One-stop console for archivists; ephemeral."""

    def __init__(self, user: nextcord.Member, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.user = user
        self.guild_id = guild_id
        self._lock_button: Button | None = None

        btn_file = Button(label="File Management", style=ButtonStyle.primary, emoji="📁")
        btn_file.callback = self.open_file_management
        self.add_item(btn_file)

        if _is_high_command(user):
            btn_bot = Button(label="Bot Management", style=ButtonStyle.success, emoji="🤖")
            btn_bot.callback = self.open_bot_management
            self.add_item(btn_bot)
            lock_btn = Button(style=ButtonStyle.danger)
            self._lock_button = lock_btn
            self._update_lock_button()
            lock_btn.callback = self.toggle_archive_lockdown
            self.add_item(lock_btn)

    def _update_lock_button(self) -> None:
        if not self._lock_button:
            return

        if is_archive_locked(self.guild_id):
            self._lock_button.label = " Release Lockdown"
            self._lock_button.emoji = "🔓"
        else:
            self._lock_button.label = " Engage Lockdown"
            self._lock_button.emoji = "🔒"

    async def toggle_archive_lockdown(self, interaction: nextcord.Interaction):
        if not _is_high_command(interaction.user):
            await interaction.response.send_message(" High Command only.", ephemeral=True)
            return

        gid = interaction.guild.id if interaction.guild else self.guild_id
        if gid is None:
            await interaction.response.send_message(
                " Cannot toggle lockdown: guild context required.", ephemeral=True
            )
            return

        locked = toggle_archive_lock(gid)
        self._update_lock_button()

        if interaction.response.is_done():
            await interaction.edit_original_message(view=self)
        else:
            await interaction.response.edit_message(view=self)

        import main

        if locked:
            message = " Archive lockdown engaged."
            gid = interaction.guild.id if interaction.guild else None
            await main.log_action(
                f" {interaction.user.mention} engaged the archive lockdown.",
                event_type="archive_lockdown",
                clearance=detect_clearance(interaction.user),
                guild_id=gid,
            )
        else:
            message = " Archive lockdown lifted."
            gid = interaction.guild.id if interaction.guild else None
            await main.log_action(
                f" {interaction.user.mention} lifted the archive lockdown.",
                event_type="archive_lockdown",
                clearance=detect_clearance(interaction.user),
                guild_id=gid,
            )

        await interaction.followup.send(message, ephemeral=True)

    async def open_file_management(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="File Management",
                description="Select an action…",
                color=0x00FFCC,
            ),
            view=FileManagementView(self),
            ephemeral=True,
        )

    async def open_bot_management(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Bot Management",
                description="Select an action…",
                color=0x00FFCC,
            ),
            view=BotManagementView(self),
            ephemeral=True,
        )

    async def open_operator_ids(self, interaction: nextcord.Interaction):
        ops = list_operators()
        if not ops:
            return await interaction.response.send_message(
                "No operator IDs found.", ephemeral=True
            )
        desc = "\n".join(
            f"<@{op.user_id}> – {op.id_code}" for op in ops
        )
        embed = Embed(
            title="Operator ID Management",
            description=desc,
            color=0x3C2E7D,
        )
        view = OperatorIDManagementView(ops, interaction.guild)
        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=True
        )

    async def open_upload(self, interaction: nextcord.Interaction):
        embed = Embed(
            title="Upload File",
            description="Step 1: Select category…",
            color=0x00FFCC,
        )
        embed.set_footer(text=ARCHIVE_FOOTER_UPLOAD)
        await interaction.response.send_message(
            embed=embed,
            view=UploadFileView(guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_formatted_upload(self, interaction: nextcord.Interaction):
        embed = Embed(
            title="Upload Formatted File",
            description="Step 1: Select category...",
            color=0x00FFCC,
        )
        embed.set_footer(text=ARCHIVE_FOOTER_UPLOAD)
        await interaction.response.send_message(
            embed=embed,
            view=UploadFileView(guild_id=self.guild_id, formatted=True),
            ephemeral=True,
        )

    async def open_remove(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Remove File",
                description="Step 1: Select category…",
                color=0xFF5555,
            ),
            view=RemoveFileView(guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_grant(self, interaction: nextcord.Interaction):
        embed = Embed(
            title="Grant Clearance",
            description="Step 1: Select category…",
            color=0x00FFCC,
        )
        embed.set_footer(text=ARCHIVE_FOOTER_CLEARANCE)
        await interaction.response.send_message(
            embed=embed,
            view=GrantClearanceView(guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_revoke(self, interaction: nextcord.Interaction):
        embed = Embed(
            title="Revoke Clearance",
            description="Step 1: Select category…",
            color=0xFF0000,
        )
        embed.set_footer(text=ARCHIVE_FOOTER_CLEARANCE)
        await interaction.response.send_message(
            embed=embed,
            view=RevokeClearanceView(guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_edit(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Edit File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=EditFileView(self.user, guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_move(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Move / Rename File",
                description="Step 1: Select source category…",
                color=0x00FFCC,
            ),
            view=MoveFileView(guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_link_personnel(self, interaction: nextcord.Interaction):
        if not _is_lead_archivist(interaction.user):
            await interaction.response.send_message(
                " Lead Archivist only.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=Embed(
                title="Link File to User",
                description="Step 1: Select operator…",
                color=0x00FFCC,
            ),
            view=LinkPersonnelView(interaction.guild),
            ephemeral=True,
        )

    async def open_annotate(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Annotate File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=AnnotateFileView(self.user, guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_categories(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Category Management",
                description="Select an action…",
                color=0x00FFCC,
            ),
            view=CategoryManagementView(self),
            ephemeral=True,
        )

    async def open_create_backup(self, interaction: nextcord.Interaction):
        from spectre.commands.archivist import _active_context
        from spectre.tasks.backups import backup_action

        context = _active_context
        if context is None:
            return await interaction.response.send_message(
                " Backup service unavailable. Please try again later.",
                ephemeral=True,
            )
        guild_id = interaction.guild.id if interaction.guild else self.guild_id
        await interaction.response.defer(ephemeral=True)
        try:
            await backup_action(context, guild_id=guild_id)
            await interaction.followup.send(
                " Backup created successfully.",
                ephemeral=True,
            )
        except Exception as e:
            import traceback

            await interaction.followup.send(
                f" Backup failed: {e}",
                ephemeral=True,
            )
            import main

            gid = interaction.guild.id if interaction.guild else self.guild_id
            await main.log_action(
                f" Create backup error: {e}\n```{traceback.format_exc()[:1800]}```",
                guild_id=gid,
            )

    async def open_backup(self, interaction: nextcord.Interaction):
        guild_id = interaction.guild.id if interaction.guild else self.guild_id
        await interaction.response.send_message(
            embed=Embed(
                title="Load Backup",
                description="Select backup to restore…",
                color=0x00FFCC,
            ),
            view=LoadBackupView(guild_id=guild_id),
            ephemeral=True,
        )

    async def open_archived(self, interaction: nextcord.Interaction):
        cats = _archived_categories_for_select(guild_id=self.guild_id)
        if not cats:
            await interaction.response.send_message(
                embed=Embed(
                    title="Archived Files",
                    description="No archived files found.",
                    color=0x888888,
                ),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=Embed(
                title="Archived Files",
                description="Select archived category…",
                color=0x888888,
            ),
            view=ViewArchivedFilesView(cats, guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_restore(self, interaction: nextcord.Interaction):
        cats = _archived_categories_for_select(guild_id=self.guild_id)
        if not cats:
            await interaction.response.send_message(
                embed=Embed(
                    title="Restore Archived File",
                    description="No archived files found.",
                    color=0x888888,
                ),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=Embed(
                title="Restore Archived File",
                description="Select archived category…",
                color=0x888888,
            ),
            view=RestoreArchivedFileView(cats, guild_id=self.guild_id),
            ephemeral=True,
        )

    async def summon_menus(self, interaction: nextcord.Interaction):
        await _summon_menus(interaction)


class ArchivistLimitedConsoleView(View):
    """Limited console for regular archivists; ephemeral."""

    def __init__(self, user: nextcord.Member, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.user = user
        self.guild_id = guild_id

        # Row 1: File creation & modification (primary workflow)
        self.btn_upload = Button(label="Upload File", style=ButtonStyle.primary, emoji="📤")
        self.btn_upload.callback = self.open_upload
        self.add_item(self.btn_upload)

        self.btn_formatted_upload = Button(label="Upload Formatted File", style=ButtonStyle.success)
        self.btn_formatted_upload.callback = self.open_formatted_upload
        self.add_item(self.btn_formatted_upload)

        self.btn_edit = Button(label="Edit File", style=ButtonStyle.secondary, emoji="✏️")
        self.btn_edit.callback = self.open_edit
        self.add_item(self.btn_edit)

        self.btn_move = Button(label="Move/Rename", style=ButtonStyle.secondary, emoji="📁")
        self.btn_move.callback = self.open_move
        self.add_item(self.btn_move)

        self.btn_annotate = Button(label="Annotate", style=ButtonStyle.secondary, emoji="📝")
        self.btn_annotate.callback = self.open_annotate
        self.add_item(self.btn_annotate)

        self.btn_archive = Button(label="Archive File", style=ButtonStyle.success, emoji="🗃️")
        self.btn_archive.callback = self.open_archive
        self.add_item(self.btn_archive)

        # Row 2: Support & deployment
        self.btn_request = Button(label="Report Problem", style=ButtonStyle.secondary, emoji="⚠️")
        self.btn_request.callback = self.open_report_problem
        self.add_item(self.btn_request)

        self.btn_summon = Button(label="Summon Menus", style=ButtonStyle.secondary, emoji="🔄")
        self.btn_summon.callback = self.summon_menus
        self.add_item(self.btn_summon)

    async def open_upload(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Upload File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=UploadFileView(allowed_roles=None, guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_formatted_upload(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Upload Formatted File",
                description="Step 1: Select category...",
                color=0x00FFCC,
            ),
            view=UploadFileView(
                allowed_roles=None,
                guild_id=self.guild_id,
                formatted=True,
            ),
            ephemeral=True,
        )

    async def open_archive(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Archive File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=ArchiveFileView(guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_edit(self, interaction: nextcord.Interaction):
        gid = self.guild_id or (getattr(interaction.guild, "id", None) if interaction.guild else None)
        has_archivist = _is_archivist(interaction.user, guild_id=gid)
        now = time.time()
        user_id = interaction.user.id
        if has_archivist and now - _last_edit_verified.get(user_id, 0) < 600:
            await interaction.response.send_message(
                embed=Embed(
                    title="Edit File",
                    description="Step 1: Select category…",
                    color=0x00FFCC,
                ),
                view=EditFileView(
                    interaction.user,
                    limit_edits=True,
                    guild_id=self.guild_id,
                ),
                ephemeral=True,
            )
            return
        try:
            if has_archivist:
                _last_edit_verified[user_id] = now
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send(
                embed=Embed(
                    title=" Running security clearance protocols…",
                    description=(
                        "Authenticating operator ID against the command relay.\n"
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
                        "> Uplink established to SPECTRE Command Systems\n"
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
                    view=EditFileView(
                        interaction.user,
                        limit_edits=True,
                        guild_id=self.guild_id,
                    ),
                )
                _last_edit_verified[user_id] = time.time()
            else:
                await msg.edit(
                    embed=Embed(
                        description=(
                            "> ACCESS OVERRIDE FAILED\n"
                            "> Operator clearance level insufficient.\n"
                            "> All attempts have been logged by SPECTRE Security Command."
                        ),
                        color=0xFF5555,
                    ),
                    view=None,
                )
                _last_edit_verified.pop(user_id, None)
        except Exception as e:
            import main
            gid = self.guild_id or (interaction.guild.id if interaction.guild else None)
            await main.log_action(
                f" open_edit error: {e}\n```{traceback.format_exc()[:1800]}```",
                guild_id=gid,
            )
            if has_archivist:
                _last_edit_verified.pop(user_id, None)
            try:
                await interaction.followup.send(
                    " Could not open editor (see log).", ephemeral=True
                )
            except Exception:
                pass

    async def open_move(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Move / Rename File",
                description="Step 1: Select source category…",
                color=0x00FFCC,
            ),
            view=MoveFileView(),
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
        gid = getattr(interaction.guild, "id", None) if interaction.guild else None
        if not _is_lead_archivist(interaction.user, guild_id=gid):
            await interaction.response.send_message(" Lead Archivist only.", ephemeral=True)
            return False
        return True

    async def approve(self, interaction: nextcord.Interaction):
        if not await self._check_role(interaction):
            return
        data = await run_blocking(_load_submission, self.user_id, self.sub_id)
        action = data.get("action", {})
        try:
            guild_id = action.get("guild_id")
            if action.get("type") == "upload":
                try:
                    key = await run_blocking(
                        create_dossier_file,
                        action["category"],
                        action["item"],
                        action.get("content", ""),
                        True,
                        guild_id,
                    )
                except TypeError:
                    key = await run_blocking(
                        create_dossier_file,
                        action["category"],
                        action["item"],
                        action.get("content", ""),
                        True,
                    )
                role_id = action.get("role_id")
                if role_id:
                    await run_blocking(
                        grant_file_clearance,
                        action["category"],
                        _strip_ext(action["item"]),
                        role_id,
                    )
            elif action.get("type") == "edit":
                try:
                    await run_blocking(
                        update_dossier_raw,
                        action["category"],
                        _strip_ext(action["item"]),
                        action.get("content", ""),
                        guild_id=guild_id,
                    )
                except TypeError:
                    await run_blocking(
                        update_dossier_raw,
                        action["category"],
                        _strip_ext(action["item"]),
                        action.get("content", ""),
                    )
            elif action.get("type") == "archive":
                try:
                    await run_blocking(
                        archive_dossier_file,
                        action["category"],
                        _strip_ext(action["item"]),
                        guild_id=guild_id,
                    )
                except TypeError:
                    await run_blocking(
                        archive_dossier_file,
                        action["category"],
                        _strip_ext(action["item"]),
                    )
            elif action.get("type") == "annotate":
                await run_blocking(
                    add_file_annotation,
                    action["category"],
                    _strip_ext(action["item"]),
                    self.user_id,
                    action.get("content", ""),
                )
            await run_blocking(_complete_submission, self.user_id, self.sub_id, "approved")
            await interaction.response.send_message(" Submission approved.", ephemeral=True)
            import main

            gid = interaction.guild.id if interaction.guild else None
            await main.log_action(
                f" {interaction.user.mention} approved trainee submission {self.sub_id}.",
                event_type="trainee_submission",
                clearance=detect_clearance(interaction.user),
                guild_id=gid,
            )
        except Exception as e:
            import main, traceback
            gid = interaction.guild.id if interaction.guild else None
            await main.log_action(
                f" trainee approve error: {e}\n```{traceback.format_exc()[:1800]}```",
                guild_id=gid,
            )
            await interaction.response.send_message(
                " Failed to apply action (see log).", ephemeral=True
            )
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
        data = await run_blocking(
            _load_submission, self.parent_view.user_id, self.parent_view.sub_id
        )
        action = data.get("action", {})
        await run_blocking(
            _complete_submission,
            self.parent_view.user_id,
            self.parent_view.sub_id,
            "denied",
            reason,
        )
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
                    f" Your submission {self.parent_view.sub_id} was denied.\nReason: {reason}",
                    file=file,
                )
            except Exception:
                pass
        await interaction.response.send_message("Submission denied.", ephemeral=True)
        import main

        gid = interaction.guild.id if interaction.guild else None
        await main.log_action(
            f" {interaction.user.mention} denied trainee submission {self.parent_view.sub_id}: {reason}",
            event_type="trainee_submission",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
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
        data = await run_blocking(
            _load_submission, self.parent_view.user_id, self.parent_view.sub_id
        )
        data["reason"] = reason
        await run_blocking(
            save_json,
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
                    f" Changes requested for your submission {self.parent_view.sub_id}.\nReason: {reason}",
                    file=file,
                )
            except Exception:
                pass
        await interaction.response.send_message("Changes requested.", ephemeral=True)
        import main

        gid = getattr(interaction.guild, "id", None) if interaction.guild else None
        await main.log_action(
            f" {interaction.user.mention} requested changes for trainee submission {self.parent_view.sub_id}: {reason}",
            event_type="trainee_submission",
            clearance=detect_clearance(interaction.user),
            guild_id=gid,
        )


async def _notify_leads(interaction: nextcord.Interaction, sub_id: str, action: dict) -> None:
    guild_id = interaction.guild.id if interaction.guild else None
    if not guild_id:
        return
    cfg = get_server_config(guild_id)
    channel_id = _coerce_int(cfg.get("LEAD_NOTIFICATION_CHANNEL_ID")) or LEAD_NOTIFICATION_CHANNEL_ID
    if not channel_id:
        return
    channel = interaction.guild.get_channel(channel_id) if interaction.guild else None
    if not channel and interaction.client:
        try:
            channel = await interaction.client.fetch_channel(channel_id)
        except Exception:
            channel = None
    if channel:
        desc = (
            f"{interaction.user.mention} submitted **{action.get('type', 'task').upper()}** for "
            f"`{action.get('category')}/{action.get('item')}`.\n\n"
            f"**Submission ID:** `{sub_id}`"
        )
        embed = Embed(title="Trainee Submission — Review Required", description=desc, color=0x00FFCC)
        content = action.get("content")
        if content:
            preview = (content[:990] + "…") if len(content) > 990 else content
            embed.add_field(
                name="Content preview",
                value=f"```\n{preview}\n```" if preview.strip() else "\u200b",
                inline=False,
            )
        embed.set_footer(text="Use the buttons below to approve, request changes, or deny.")
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
            "content": PAGE_SEPARATOR.join(self.modal.pages),
            "role_id": self.modal.parent_view.role_id,
            "guild_id": self.modal.parent_view.guild_id,
        }
        sub_id = await run_blocking(_save_submission, interaction.user.id, action)
        await interaction.response.send_message(
            " Submission pending lead review.", ephemeral=True
        )
        await _notify_leads(interaction, sub_id, action)


class TraineeUploadFileView(View):
    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.category: str | None = None
        self.role_id: int | None = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
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
        allowed_ids = set(_assignable_role_ids(self.guild_id))
        roles = [r for r in interaction.guild.roles if r.id in allowed_ids]
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
            "guild_id": self.parent_view.guild_id,
        }
        sub_id = await run_blocking(_save_submission, interaction.user.id, action)
        await interaction.response.send_message(
            " Submission pending lead review.", ephemeral=True
        )
        await _notify_leads(interaction, sub_id, action)


class TraineeEditFileView(View):
    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.category: str | None = None
        self.item: str | None = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
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
        items = list_items_recursive(self.category, guild_id=self.guild_id)
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
        found = _find_existing_item_key(
            self.category,
            self.item,
            guild_id=self.guild_id,
        )
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
    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.category: str | None = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
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
        items = list_items_recursive(self.category, guild_id=self.guild_id)
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
            "guild_id": self.guild_id,
        }
        sub_id = await run_blocking(_save_submission, interaction.user.id, action)
        await interaction.response.send_message(
            " Submission pending lead review.", ephemeral=True
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
            "guild_id": self.parent_view.guild_id,
        }
        sub_id = await run_blocking(_save_submission, interaction.user.id, action)
        await interaction.response.send_message(
            " Submission pending lead review.", ephemeral=True
        )
        await _notify_leads(interaction, sub_id, action)


class TraineeAnnotateFileView(View):
    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.guild_id = guild_id
        self.category: str | None = None
        self.item: str | None = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in _categories_for_select(guild_id=self.guild_id)
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
        items = list_items_recursive(self.category, guild_id=self.guild_id)
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
    def __init__(self, user: nextcord.Member, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.user = user
        self.guild_id = guild_id

        btn_u = Button(label=" Upload File", style=ButtonStyle.primary)
        btn_u.callback = self.open_upload
        self.add_item(btn_u)

        btn_e = Button(label=" Edit File", style=ButtonStyle.secondary)
        btn_e.callback = self.open_edit
        self.add_item(btn_e)

        btn_a = Button(label=" Archive File", style=ButtonStyle.secondary)
        btn_a.callback = self.open_archive
        self.add_item(btn_a)

        btn_n = Button(label=" Annotate File", style=ButtonStyle.secondary)
        btn_n.callback = self.open_annotate
        self.add_item(btn_n)

    async def open_upload(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Upload File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=TraineeUploadFileView(guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_edit(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Edit File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=TraineeEditFileView(guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_archive(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Archive File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=TraineeArchiveFileView(guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_annotate(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="Annotate File",
                description="Step 1: Select category…",
                color=0x00FFCC,
            ),
            view=TraineeAnnotateFileView(guild_id=self.guild_id),
            ephemeral=True,
        )


class ArchivistTraineeConsoleView(View):
    """Console for Archivist trainees; actions require approval."""

    def __init__(self, user: nextcord.Member, guild_id: int | None = None):
        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self.user = user
        self.guild_id = guild_id

        btn_start = Button(label=" Start Task", style=ButtonStyle.primary)
        btn_start.callback = self.open_start
        self.add_item(btn_start)

        btn_pending = Button(label=" Pending Submissions", style=ButtonStyle.secondary)
        btn_pending.callback = self.open_pending
        self.add_item(btn_pending)

        btn_completed = Button(label=" Completed Tasks", style=ButtonStyle.secondary)
        btn_completed.callback = self.open_completed
        self.add_item(btn_completed)

        btn_help = Button(label=" Help", style=ButtonStyle.secondary)
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
            "[ Upload File] [ Edit File] [ Archive File]\n"
            "[ Annotate File] \n"
            "─────────────────────────────────────"
        )
        await interaction.response.send_message(
            text,
            view=TraineeTaskSelectView(self.user, guild_id=self.guild_id),
            ephemeral=True,
        )

    async def open_pending(self, interaction: nextcord.Interaction):
        subs = await run_blocking(_list_submissions, interaction.user.id, "pending")
        desc = "\n".join(
            f"`{s['id']}` {s['action'].get('type')} {s['action'].get('category')}/{s['action'].get('item')}"
            for s in subs
        ) or "(none)"
        embed = Embed(title="Pending Submissions", description=desc, color=0x00FFCC)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def open_completed(self, interaction: nextcord.Interaction):
        subs = await run_blocking(_list_submissions, interaction.user.id, "completed")
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
        return await message.channel.send(" Add the category name in the message text.")
    # ``list_categories`` performs I/O through the storage backend which can
    # block the event loop when using network services (e.g. S3).  Offload the
    # call to a worker thread to keep the bot responsive during uploads.
    guild_obj = getattr(message, "guild", None)
    guild_id = getattr(guild_obj, "id", None)
    categories = await asyncio.to_thread(list_categories, guild_id)
    if category not in categories:
        return await message.channel.send(f" Unknown category `{category}`.")

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
            # ``create_dossier_file`` may touch remote storage.  Running it in a
            # thread prevents long network calls from freezing other
            # interactions.

            def _create(category, item_rel_input, data, prefer_txt_default, gid):
                try:
                    return create_dossier_file(
                        category,
                        item_rel_input,
                        data,
                        prefer_txt_default,
                        guild_id=gid,
                    )
                except TypeError:
                    return create_dossier_file(
                        category, item_rel_input, data, prefer_txt_default
                    )

            key = await asyncio.to_thread(
                _create,
                category,
                item_rel_input,
                data,
                not is_json,
                guild_id,
            )
        except FileExistsError:
            await message.channel.send(f" `{item_rel_input}` already exists.")
        else:
            await message.channel.send(f" Added `{item_rel_input}` to `{category}`.")
            import main

            clearance = detect_clearance(message.author) if hasattr(message.author, "roles") else None
            await main.log_action(
                f" {message.author.mention} uploaded `{category}/{item_rel_input}` → `{key}`.",
                event_type="file_upload",
                clearance=clearance,
                guild_id=guild_id,
            )
            processed = True

    if not processed:
        await message.channel.send(" No .json/.txt files found in the upload.")
