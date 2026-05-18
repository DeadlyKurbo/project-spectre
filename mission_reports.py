"""Mission report submission, review, and archive workflow."""

from __future__ import annotations

import os
import random
from datetime import datetime, timezone
from typing import Any

import nextcord
from nextcord import ButtonStyle, Embed, Interaction, TextInputStyle
from nextcord.ui import Button, Modal, Select, TextInput, View

from acl import grant_file_clearance
from archivist import _coerce_int, _is_lead_archivist, _role_ids
from async_utils import run_blocking
from dossier import create_dossier_file
from server_config import get_server_config, invalidate_config
from storage_spaces import delete_file, list_dir, read_json as ss_read_json, save_json

_MENU_ANCHOR_PREFIX = "system/mission_reports_menu_anchors"

_REPORT_PREFIX = "mission_reports"
_CODENAMES = [
    "Falcon", "Viper", "Ghost", "Specter", "Titan", "Saber", "Raven", "Phantom",
    "Hunter", "Nomad", "Reaper", "Talon", "Outlaw", "Raptor", "Sentinel",
    "Paladin", "Wraith", "Maverick", "Bishop", "Oracle",
]


def _guild_prefix(guild_id: int) -> str:
    return f"{_REPORT_PREFIX}/{guild_id}"


def _report_key(guild_id: int, status: str, report_id: str) -> str:
    return f"{_guild_prefix(guild_id)}/{status}/{report_id}.json"


def _mission_reports_cfg(guild_id: int | None) -> dict[str, Any]:
    cfg = get_server_config(guild_id or 0)
    block = cfg.get("mission_reports")
    return block if isinstance(block, dict) else {}


def is_mission_reports_enabled(guild_id: int | None) -> bool:
    cfg = get_server_config(guild_id or 0)
    if cfg.get("MISSION_REPORTS_ENABLED") is True:
        return True
    block = _mission_reports_cfg(guild_id)
    return bool(block.get("enabled"))


def _role_list_from_cfg(cfg: dict[str, Any], key: str) -> list[int]:
    raw = cfg.get(key)
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for item in raw:
        coerced = _coerce_int(item)
        if coerced and coerced not in out:
            out.append(coerced)
    return out


def _configured_role_ids(guild_id: int | None, flat_key: str, nested_key: str) -> list[int]:
    cfg = get_server_config(guild_id or 0)
    flat = cfg.get(flat_key)
    if isinstance(flat, list) and flat:
        return _role_list_from_cfg({nested_key: flat}, nested_key)
    return _role_list_from_cfg(_mission_reports_cfg(guild_id), nested_key)


def can_submit(user: nextcord.Member, guild_id: int | None = None) -> bool:
    if not is_mission_reports_enabled(guild_id):
        return False
    roles = _role_ids(user)
    submitter_roles = _configured_role_ids(
        guild_id, "MISSION_REPORTS_SUBMITTER_ROLES", "submitter_roles"
    )
    if not submitter_roles:
        return False
    return bool(roles.intersection(submitter_roles))


def can_review(user: nextcord.Member, guild_id: int | None = None) -> bool:
    if not is_mission_reports_enabled(guild_id):
        return False
    reviewer_roles = _configured_role_ids(
        guild_id, "MISSION_REPORTS_REVIEWER_ROLES", "reviewer_roles"
    )
    if reviewer_roles and _role_ids(user).intersection(reviewer_roles):
        return True
    return _is_lead_archivist(user, guild_id=guild_id)


def _generate_report_id(guild_id: int) -> str:
    _, pending = list_dir(f"{_guild_prefix(guild_id)}/pending")
    _, approved = list_dir(f"{_guild_prefix(guild_id)}/approved")
    _, completed = list_dir(f"{_guild_prefix(guild_id)}/completed")
    existing = {
        os.path.splitext(name)[0]
        for name, _ in pending + approved + completed
    }
    while True:
        codename = random.choice(_CODENAMES)
        number = random.randint(0, 99)
        report_id = f"MR-{codename}-{number:02d}"
        if report_id not in existing:
            return report_id


def save_report(guild_id: int, submitter_id: int, fields: dict[str, str]) -> str:
    report_id = _generate_report_id(guild_id)
    data = {
        "id": report_id,
        "guild_id": guild_id,
        "submitter_id": submitter_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "fields": fields,
        "review": {"reviewer_id": None, "reviewed_at": None, "reason": None},
        "archive": {"category": None, "item": None, "archived_at": None},
    }
    save_json(_report_key(guild_id, "pending", report_id), data)
    return report_id


def load_report(guild_id: int, report_id: str, status: str = "pending") -> dict[str, Any]:
    return ss_read_json(_report_key(guild_id, status, report_id))


def _move_report(guild_id: int, report_id: str, from_status: str, to_status: str) -> dict[str, Any]:
    data = load_report(guild_id, report_id, from_status)
    save_json(_report_key(guild_id, to_status, report_id), data)
    delete_file(_report_key(guild_id, from_status, report_id))
    return data


def complete_report(
    guild_id: int,
    report_id: str,
    from_status: str,
    final_status: str,
    *,
    reason: str | None = None,
    reviewer_id: int | None = None,
) -> dict[str, Any]:
    data = load_report(guild_id, report_id, from_status)
    data["status"] = final_status
    review = data.get("review") if isinstance(data.get("review"), dict) else {}
    review["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    if reviewer_id is not None:
        review["reviewer_id"] = reviewer_id
    if reason is not None:
        review["reason"] = reason
    data["review"] = review
    save_json(_report_key(guild_id, "completed", report_id), data)
    delete_file(_report_key(guild_id, from_status, report_id))
    return data


def list_reports(guild_id: int, status: str) -> list[dict[str, Any]]:
    prefix = f"{_guild_prefix(guild_id)}/{status}"
    try:
        _, files = list_dir(prefix)
    except Exception:
        return []
    reports: list[dict[str, Any]] = []
    for name, _size in files:
        report_id = os.path.splitext(name)[0]
        try:
            reports.append(load_report(guild_id, report_id, status))
        except Exception:
            continue
    return reports


def format_report_for_dossier(fields: dict[str, str], meta: dict[str, Any]) -> str:
    lines = [
        "MISSION REPORT",
        "==============",
        f"Report ID: {meta.get('id', 'unknown')}",
        f"Submitted: {meta.get('submitted_at', '—')}",
        f"Submitter: <@{meta.get('submitter_id', '0')}>",
        "",
        f"Mission: {fields.get('mission_name', '—')}",
        f"Date: {fields.get('date', '—')}",
        "",
        "Objectives",
        "----------",
        fields.get("objectives", "—"),
        "",
        "Outcome",
        "-------",
        fields.get("outcome", "—"),
        "",
        "Notes",
        "-----",
        fields.get("notes", "—") or "—",
    ]
    return "\n".join(lines)


def _review_channel_id(guild_id: int) -> int | None:
    cfg = get_server_config(guild_id)
    channel = _coerce_int(cfg.get("MISSION_REPORTS_REVIEW_CHANNEL_ID"))
    if channel:
        return channel
    block = _mission_reports_cfg(guild_id)
    return _coerce_int(block.get("review_channel"))


def _archive_category(guild_id: int) -> str:
    block = _mission_reports_cfg(guild_id)
    cat = block.get("archive_category")
    if isinstance(cat, str) and cat.strip():
        return cat.strip()
    return "missions"


def _default_clearance_role(guild_id: int) -> int | None:
    block = _mission_reports_cfg(guild_id)
    return _coerce_int(block.get("default_clearance_role"))


def _menu_channel_id(guild_id: int) -> int | None:
    cfg = get_server_config(guild_id)
    channel = _coerce_int(cfg.get("MISSION_REPORTS_MENU_CHANNEL_ID"))
    if channel:
        return channel
    block = _mission_reports_cfg(guild_id)
    return _coerce_int(block.get("menu_channel"))


def _menu_anchor_path(guild_id: int) -> str:
    return f"{_MENU_ANCHOR_PREFIX}/{int(guild_id)}.json"


def _load_menu_anchor(guild_id: int) -> dict[str, int] | None:
    try:
        payload = ss_read_json(_menu_anchor_path(guild_id))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    channel_id = _coerce_int(payload.get("channel_id"))
    message_id = _coerce_int(payload.get("message_id"))
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
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _menu_embed(guild_id: int) -> Embed:
    cfg = get_server_config(guild_id)
    block = _mission_reports_cfg(guild_id)
    menu = block.get("menu") if isinstance(block.get("menu"), dict) else {}
    title = cfg.get("MISSION_REPORTS_MENU_TITLE")
    if not isinstance(title, str) or not title.strip():
        title = menu.get("title") if isinstance(menu.get("title"), str) else "Mission Reports"
    desc = cfg.get("MISSION_REPORTS_MENU_DESC")
    if not isinstance(desc, str) or not desc.strip():
        desc = menu.get("description") if isinstance(menu.get("description"), str) else (
            "Submit structured mission reports for command review. "
            "Approved reports are held until archived into the dossier system."
        )
    footer = cfg.get("MISSION_REPORTS_MENU_FOOTER")
    if not isinstance(footer, str) or not footer.strip():
        footer = menu.get("footer") if isinstance(menu.get("footer"), str) else None
    embed = Embed(title=title, description=desc, color=0xCC2233)
    if footer:
        embed.set_footer(text=footer)
    thumb = cfg.get("MISSION_REPORTS_MENU_THUMBNAIL")
    if not isinstance(thumb, str) or not thumb.strip():
        thumb = menu.get("thumbnail") if isinstance(menu.get("thumbnail"), str) else None
    if thumb:
        embed.set_thumbnail(url=thumb)
    return embed


async def open_submit_flow(interaction: Interaction) -> None:
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("Guild context required.", ephemeral=True)
        return
    gid = guild.id
    if not is_mission_reports_enabled(gid):
        await interaction.response.send_message(
            "Mission reports are not enabled on this server.", ephemeral=True
        )
        return
    member = interaction.user if isinstance(interaction.user, nextcord.Member) else None
    if not member or not can_submit(member, gid):
        await interaction.response.send_message(
            "You do not have permission to submit mission reports.", ephemeral=True
        )
        return
    await interaction.response.send_modal(MissionReportModal(gid))


class MissionReportModal(Modal):
    def __init__(self, guild_id: int):
        super().__init__(title="Submit Mission Report", timeout=600)
        self.guild_id = guild_id
        self.mission_name = TextInput(label="Mission name", max_length=200)
        self.date = TextInput(label="Date", max_length=100)
        self.objectives = TextInput(
            label="Objectives",
            style=TextInputStyle.paragraph,
            max_length=1500,
        )
        self.outcome = TextInput(
            label="Outcome",
            style=TextInputStyle.paragraph,
            max_length=1500,
        )
        self.notes = TextInput(
            label="Notes (optional)",
            style=TextInputStyle.paragraph,
            required=False,
            max_length=1500,
        )
        for item in (
            self.mission_name,
            self.date,
            self.objectives,
            self.outcome,
            self.notes,
        ):
            self.add_item(item)

    async def callback(self, interaction: Interaction) -> None:
        member = interaction.user if isinstance(interaction.user, nextcord.Member) else None
        if not member or not can_submit(member, self.guild_id):
            await interaction.response.send_message("Permission denied.", ephemeral=True)
            return
        fields = {
            "mission_name": self.mission_name.value.strip(),
            "date": self.date.value.strip(),
            "objectives": self.objectives.value.strip(),
            "outcome": self.outcome.value.strip(),
            "notes": (self.notes.value or "").strip(),
        }
        if not all(fields[k] for k in ("mission_name", "date", "objectives", "outcome")):
            await interaction.response.send_message(
                "Mission name, date, objectives, and outcome are required.", ephemeral=True
            )
            return
        report_id = await run_blocking(save_report, self.guild_id, member.id, fields)
        await interaction.response.send_message(
            f"Mission report `{report_id}` submitted for review.", ephemeral=True
        )
        await _notify_reviewers(interaction, report_id, fields)
        try:
            import main

            await main.log_action(
                f"{interaction.user.mention} submitted mission report `{report_id}`.",
                event_type="mission_report_submit",
                guild_id=self.guild_id,
            )
        except Exception:
            pass


class MissionReportReviewView(View):
    def __init__(self, guild_id: int, report_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.report_id = report_id
        self.message: nextcord.Message | None = None

        approve = Button(
            label="Approve",
            style=ButtonStyle.success,
            custom_id=f"mr_approve:{guild_id}:{report_id}",
        )
        approve.callback = self.approve
        self.add_item(approve)

        changes = Button(
            label="Request Changes",
            style=ButtonStyle.secondary,
            custom_id=f"mr_changes:{guild_id}:{report_id}",
        )
        changes.callback = self.request_changes
        self.add_item(changes)

        deny = Button(
            label="Deny",
            style=ButtonStyle.danger,
            custom_id=f"mr_deny:{guild_id}:{report_id}",
        )
        deny.callback = self.deny
        self.add_item(deny)

    async def _check_role(self, interaction: Interaction) -> bool:
        member = interaction.user if isinstance(interaction.user, nextcord.Member) else None
        if not member or not can_review(member, self.guild_id):
            await interaction.response.send_message("Reviewer access required.", ephemeral=True)
            return False
        return True

    async def approve(self, interaction: Interaction) -> None:
        if not await self._check_role(interaction):
            return
        try:
            data = await run_blocking(
                _move_report, self.guild_id, self.report_id, "pending", "approved"
            )
            data["status"] = "approved"
            save_json(_report_key(self.guild_id, "approved", self.report_id), data)
        except Exception:
            await interaction.response.send_message(
                "Report not found or already processed.", ephemeral=True
            )
            return
        await _dm_submitter(
            interaction,
            data.get("submitter_id"),
            f"Your mission report `{self.report_id}` was approved and awaits archival.",
        )
        await interaction.response.send_message("Report approved.", ephemeral=True)
        await _disable_view(interaction)
        await _log_review(interaction, "approved")

    async def request_changes(self, interaction: Interaction) -> None:
        if not await self._check_role(interaction):
            return
        self.message = interaction.message
        await interaction.response.send_modal(MissionReportChangesModal(self))

    async def deny(self, interaction: Interaction) -> None:
        if not await self._check_role(interaction):
            return
        self.message = interaction.message
        await interaction.response.send_modal(MissionReportDenyModal(self))


class MissionReportDenyModal(Modal):
    def __init__(self, parent: MissionReportReviewView):
        super().__init__(title="Deny Mission Report")
        self.parent = parent
        self.reason = TextInput(
            label="Reason",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=1000,
        )
        self.add_item(self.reason)

    async def callback(self, interaction: Interaction) -> None:
        if not await self.parent._check_role(interaction):
            return
        reason = self.reason.value.strip()
        try:
            data = await run_blocking(
                complete_report,
                self.parent.guild_id,
                self.parent.report_id,
                "pending",
                "denied",
                reason=reason,
                reviewer_id=interaction.user.id,
            )
        except Exception:
            await interaction.response.send_message("Report not found.", ephemeral=True)
            return
        await _dm_submitter(
            interaction,
            data.get("submitter_id"),
            f"Your mission report `{self.parent.report_id}` was denied.\nReason: {reason}",
        )
        await interaction.response.send_message("Report denied.", ephemeral=True)
        await _disable_view(interaction, self.parent)
        await _log_review(interaction, "denied", reason)


class MissionReportChangesModal(Modal):
    def __init__(self, parent: MissionReportReviewView):
        super().__init__(title="Request Changes")
        self.parent = parent
        self.reason = TextInput(
            label="Reason",
            style=TextInputStyle.paragraph,
            min_length=1,
            max_length=1000,
        )
        self.add_item(self.reason)

    async def callback(self, interaction: Interaction) -> None:
        if not await self.parent._check_role(interaction):
            return
        reason = self.reason.value.strip()
        try:
            data = await run_blocking(
                load_report, self.parent.guild_id, self.parent.report_id, "pending"
            )
        except Exception:
            await interaction.response.send_message("Report not found.", ephemeral=True)
            return
        review = data.get("review") if isinstance(data.get("review"), dict) else {}
        review["reason"] = reason
        review["reviewer_id"] = interaction.user.id
        data["review"] = review
        data["status"] = "changes_requested"
        await run_blocking(
            save_json,
            _report_key(self.parent.guild_id, "pending", self.parent.report_id),
            data,
        )
        await _dm_submitter(
            interaction,
            data.get("submitter_id"),
            f"Changes requested for mission report `{self.parent.report_id}`.\nReason: {reason}",
        )
        await interaction.response.send_message("Changes requested.", ephemeral=True)
        await _log_review(interaction, "changes_requested", reason)


class MissionReportMenuView(View):
    """Standalone mission reports menu (optional dedicated channel)."""

    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        submit = Button(
            label="Submit Report",
            style=ButtonStyle.primary,
            custom_id=f"mr_submit:{guild_id}",
        )
        submit.callback = self._submit
        self.add_item(submit)
        archive = Button(
            label="Archive Queue",
            style=ButtonStyle.secondary,
            custom_id=f"mr_queue:{guild_id}",
        )
        archive.callback = self._archive_queue
        self.add_item(archive)

    async def _submit(self, interaction: Interaction) -> None:
        await open_submit_flow(interaction)

    async def _archive_queue(self, interaction: Interaction) -> None:
        member = interaction.user if isinstance(interaction.user, nextcord.Member) else None
        if not member or not can_review(member, self.guild_id):
            await interaction.response.send_message("Reviewer access required.", ephemeral=True)
            return
        approved = await run_blocking(list_reports, self.guild_id, "approved")
        if not approved:
            await interaction.response.send_message(
                "No approved reports awaiting archive.", ephemeral=True
            )
            return
        view = MissionReportArchiveSelectView(self.guild_id, approved[:25])
        await interaction.response.send_message(
            "Select a report to archive into the dossier system:",
            view=view,
            ephemeral=True,
        )


class MissionReportArchiveSelectView(View):
    def __init__(self, guild_id: int, reports: list[dict[str, Any]]):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        options = []
        for report in reports[:25]:
            rid = report.get("id", "?")
            fields = report.get("fields") if isinstance(report.get("fields"), dict) else {}
            name = fields.get("mission_name", rid)
            options.append(nextcord.SelectOption(label=str(name)[:100], value=str(rid)))
        if not options:
            return
        select = Select(placeholder="Choose a report…", options=options, min_values=1, max_values=1)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: Interaction) -> None:
        member = interaction.user if isinstance(interaction.user, nextcord.Member) else None
        if not member or not can_review(member, self.guild_id):
            await interaction.response.send_message("Reviewer access required.", ephemeral=True)
            return
        report_id = self.children[0].values[0]
        await interaction.response.send_modal(
            MissionReportArchiveConfirmModal(self.guild_id, report_id)
        )


class MissionReportArchiveConfirmModal(Modal):
    def __init__(self, guild_id: int, report_id: str):
        super().__init__(title="Archive to Dossier")
        self.guild_id = guild_id
        self.report_id = report_id
        self.item_name = TextInput(
            label="Dossier file name",
            default=report_id.replace(" ", "_"),
            max_length=200,
        )
        self.add_item(self.item_name)

    async def callback(self, interaction: Interaction) -> None:
        member = interaction.user if isinstance(interaction.user, nextcord.Member) else None
        if not member or not can_review(member, self.guild_id):
            await interaction.response.send_message("Reviewer access required.", ephemeral=True)
            return
        item = self.item_name.value.strip()
        if not item:
            await interaction.response.send_message("File name required.", ephemeral=True)
            return
        try:
            data = await run_blocking(load_report, self.guild_id, self.report_id, "approved")
        except Exception:
            await interaction.response.send_message(
                "Report not found in approved queue.", ephemeral=True
            )
            return
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
        content = format_report_for_dossier(fields, data)
        category = _archive_category(self.guild_id)
        try:
            await run_blocking(
                create_dossier_file,
                category,
                item,
                content,
                True,
                self.guild_id,
            )
        except TypeError:
            await run_blocking(create_dossier_file, category, item, content, True)
        clearance_role = _default_clearance_role(self.guild_id)
        if clearance_role:
            try:
                await run_blocking(
                    grant_file_clearance,
                    category,
                    os.path.splitext(item)[0],
                    clearance_role,
                )
            except Exception:
                pass
        archive = data.get("archive") if isinstance(data.get("archive"), dict) else {}
        archive["category"] = category
        archive["item"] = item
        archive["archived_at"] = datetime.now(timezone.utc).isoformat()
        data["archive"] = archive
        await run_blocking(
            complete_report,
            self.guild_id,
            self.report_id,
            "approved",
            "archived",
            reviewer_id=interaction.user.id,
        )
        await interaction.response.send_message(
            f"Report `{self.report_id}` archived to `{category}/{item}`.", ephemeral=True
        )
        try:
            import main

            await main.log_action(
                f"{interaction.user.mention} archived mission report `{self.report_id}` "
                f"to `{category}/{item}`.",
                event_type="mission_report_archive",
                guild_id=self.guild_id,
            )
        except Exception:
            pass


async def _notify_reviewers(
    interaction: Interaction, report_id: str, fields: dict[str, str]
) -> None:
    guild = interaction.guild
    if not guild:
        return
    channel_id = _review_channel_id(guild.id)
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not channel and interaction.client:
        try:
            channel = await interaction.client.fetch_channel(channel_id)
        except Exception:
            channel = None
    if not channel:
        return
    desc = (
        f"{interaction.user.mention} submitted mission report "
        f"**{fields.get('mission_name', report_id)}**.\n"
        f"**Report ID:** `{report_id}`\n"
        f"**Date:** {fields.get('date', '—')}\n\n"
        f"**Objectives:**\n{fields.get('objectives', '—')[:500]}\n\n"
        f"**Outcome:**\n{fields.get('outcome', '—')[:500]}"
    )
    embed = Embed(
        title="Mission Report — Review Required",
        description=desc,
        color=0xCC2233,
    )
    if fields.get("notes"):
        embed.add_field(name="Notes", value=fields["notes"][:1000], inline=False)
    embed.set_footer(text="Approve, request changes, or deny using the buttons below.")
    view = MissionReportReviewView(guild.id, report_id)
    try:
        await channel.send(embed=embed, view=view)
    except Exception:
        pass


async def _dm_submitter(interaction: Interaction, user_id: int | None, message: str) -> None:
    if not user_id or not interaction.guild:
        return
    user = interaction.guild.get_member(user_id)
    if not user and interaction.client:
        try:
            user = await interaction.client.fetch_user(user_id)
        except Exception:
            user = None
    if user:
        try:
            await user.send(message)
        except Exception:
            pass


async def _disable_view(interaction: Interaction, view: View | None = None) -> None:
    target = view
    if target is None and interaction.message:
        target = interaction.message.view
    if target and hasattr(target, "children"):
        for child in target.children:
            child.disabled = True
        if interaction.message:
            try:
                await interaction.message.edit(view=target)
            except Exception:
                pass


async def _log_review(interaction: Interaction, action: str, reason: str | None = None) -> None:
    try:
        import main

        msg = f"{interaction.user.mention} {action} a mission report."
        if reason:
            msg += f" Reason: {reason}"
        await main.log_action(
            msg,
            event_type="mission_report_review",
            guild_id=interaction.guild.id if interaction.guild else None,
        )
    except Exception:
        pass


async def refresh_mission_reports_menu(
    guild: nextcord.Guild, menu_channel_override: int | None = None
) -> None:
    """Deploy a fresh mission reports menu (replaces any previous anchored message)."""
    invalidate_config(guild.id)
    if not is_mission_reports_enabled(guild.id):
        raise ValueError("Mission reports are not enabled for this server.")

    stored_anchor = _load_menu_anchor(guild.id)
    preferred_ids: list[int] = []
    for candidate in (
        menu_channel_override,
        stored_anchor.get("channel_id") if isinstance(stored_anchor, dict) else None,
        _menu_channel_id(guild.id),
    ):
        coerced = _coerce_int(candidate)
        if coerced is not None and coerced not in preferred_ids:
            preferred_ids.append(coerced)
    if not preferred_ids:
        raise ValueError("No mission reports menu channel configured.")

    get_channel_or_thread = getattr(guild, "get_channel_or_thread", None)
    menu_ch = None
    resolved_channel_id: int | None = None
    for menu_channel_id in preferred_ids:
        if callable(get_channel_or_thread):
            menu_ch = get_channel_or_thread(menu_channel_id)
        else:
            menu_ch = guild.get_channel(menu_channel_id)
        if menu_ch is None:
            try:
                fetched = await guild.fetch_channel(menu_channel_id)
                menu_ch = fetched
            except Exception:
                menu_ch = None
        if menu_ch and hasattr(menu_ch, "send"):
            resolved_channel_id = menu_channel_id
            break
    else:
        raise ValueError("Configured mission reports menu channel not found.")

    try:
        guild._state._get_client().add_view(MissionReportMenuView(guild.id))
    except Exception:
        pass

    embed = _menu_embed(guild.id)
    title = embed.title

    async def _delete_message(message: object) -> bool:
        delete = getattr(message, "delete", None)
        if not callable(delete):
            return False
        try:
            await delete()
            return True
        except Exception:
            return False

    old_message_id = None
    if isinstance(stored_anchor, dict):
        old_message_id = _coerce_int(stored_anchor.get("message_id"))
    if old_message_id is not None:
        try:
            old_message = await menu_ch.fetch_message(old_message_id)
        except Exception:
            old_message = None
        if old_message is not None:
            await _delete_message(old_message)

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
                has_menu_embed = any(
                    getattr(e, "title", "") == title for e in embeds
                )
                if has_components or has_menu_embed:
                    await _delete_message(message)
        except Exception:
            pass

    sent = await menu_ch.send(embed=embed, view=MissionReportMenuView(guild.id))
    _save_menu_anchor(guild.id, menu_ch.id, sent.id)


async def deploy_mission_reports_menu(guild: nextcord.Guild) -> bool:
    """Best-effort deploy used by config watchers; returns False when skipped."""
    try:
        await refresh_mission_reports_menu(guild)
        return True
    except ValueError:
        return False
    except Exception:
        return False


def register_persistent_views(bot: nextcord.Client, guild_ids: list[int]) -> None:
    """Register persistent views for mission report buttons."""
    for gid in guild_ids:
        if not is_mission_reports_enabled(gid):
            continue
        try:
            bot.add_view(MissionReportMenuView(gid))
        except Exception:
            pass
        for status in ("pending",):
            try:
                reports = list_reports(gid, status)
            except Exception:
                reports = []
            for report in reports:
                rid = report.get("id")
                if not rid:
                    continue
                try:
                    bot.add_view(MissionReportReviewView(gid, str(rid)))
                except Exception:
                    pass
