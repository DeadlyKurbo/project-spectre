"""High-level contingency protocol commands."""

from __future__ import annotations

import nextcord

from constants import (
    CLASSIFIED_ROLE_ID,
    EPSILON_FLEET_CODE,
    EPSILON_LAUNCH_CODE,
    EPSILON_OWNER_CODE,
    EPSILON_XO_CODE,
    FLEET_ADMIRAL_ROLE_ID,
    OMEGA_BACKUP_PATH,
    OMEGA_KEY_FRAGMENT_1,
    OMEGA_KEY_FRAGMENT_2,
    OWNER_ROLE_ID,
    XO_ROLE_ID,
)
from server_config import get_server_config

from async_utils import run_blocking
from ..context import SpectreContext
from ..interactions import guild_id_from_interaction
from ..tasks.backups import purge_archive_and_backups, restore_backup


async def apply_protocol_epsilon(guild: nextcord.Guild, classified_role: nextcord.Role) -> None:
    for channel in guild.channels:
        for role in guild.roles:
            if role.position < classified_role.position:
                try:
                    await channel.set_permissions(
                        role,
                        send_messages=False,
                        add_reactions=False,
                        connect=False,
                        speak=False,
                    )
                except Exception:
                    continue


async def execute_epsilon_actions(
    context: SpectreContext, guild: nextcord.Guild, classified_role: nextcord.Role
) -> None:
    await apply_protocol_epsilon(guild, classified_role)
    await run_blocking(purge_archive_and_backups)
    await context.log_action(" Protocol EPSILON purge executed.")


async def execute_omega_actions(context: SpectreContext, guild: nextcord.Guild) -> None:
    try:
        await run_blocking(restore_backup, OMEGA_BACKUP_PATH)
        await context.log_action(" Omega Directive restoration executed.")
    except Exception as exc:
        await context.log_action(f" Omega restore error: {exc}")


async def protocol_epsilon_command(
    context: SpectreContext, interaction: nextcord.Interaction
) -> None:
    guild = getattr(interaction, "guild", None)
    fallback_id = getattr(guild, "id", 0)
    guild_id = guild_id_from_interaction(interaction) or fallback_id
    cfg = get_server_config(guild_id)
    classified_id = (
        cfg.get("CLASSIFIED_ROLE_ID", CLASSIFIED_ROLE_ID)
        if hasattr(cfg, "get")
        else CLASSIFIED_ROLE_ID
    )
    if not classified_id:
        classified_id = CLASSIFIED_ROLE_ID
    classified_role = interaction.guild.get_role(classified_id)
    if not classified_role:
        return await interaction.response.send_message(
            "Classified Clearance role not found.", ephemeral=True
        )
    if interaction.user.top_role.position < classified_role.position:
        return await interaction.response.send_message(
            " Classified clearance required.", ephemeral=True
        )

    role_ping = f"<@&{OWNER_ROLE_ID}> <@&{XO_ROLE_ID}> <@&{FLEET_ADMIRAL_ROLE_ID}>"

    warning_one = (
        f"{role_ping}\n"
        "[ACCESS NODE: EPSILON]\n"
        "> Command Detected: /protocol-epsilon\n"
        "> Warning: This action will trigger FINAL CONTINGENCY PROTOCOL.\n"
        "──────────────────────────────\n"
        "  WARNING EPSILON IS A NO-FAIL PROTOCOL\n"
        "Once initiated, all GU7 systems will:\n"
        "- Lock all archives fleet-wide\n"
        "- Terminate all active operations\n"
        "- Prepare HQ for data purge & shutdown\n\n"
        "Only Command Authority L5+ may proceed.\n"
        "──────────────────────────────"
    )

    warning_two = (
        "[FINAL WARNING: EPSILON ACTIVATION]\n"
        "This action cannot be undone.\n"
        "Confirm full protocol synchronization?"
    )

    final_screen = (
        "[EPSILON LAUNCH AUTHORIZED]\n"
        "Protocol Epsilon is now active.\n"
        "All GU7 systems shifting to Contingency Mode."
    )

    class OwnerModal(nextcord.ui.Modal):
        def __init__(self, parent_view: nextcord.ui.View):
            super().__init__(title="OWNER AUTHORIZATION")
            self.parent_view = parent_view
            self.code = nextcord.ui.TextInput(label="Owner code")
            self.add_item(self.code)

        async def callback(self, modal_interaction: nextcord.Interaction):
            if self.code.value.strip() != EPSILON_OWNER_CODE:
                return await modal_interaction.response.send_message(
                    "Authorization failed.", ephemeral=True
                )
            self.parent_view.owner_confirmed = True
            for child in self.parent_view.children:
                if isinstance(child, nextcord.ui.Button) and child.label == "OWNER CONFIRM":
                    child.disabled = True
                    break
            warning_msg = (
                f"\U0001F6A8{modal_interaction.user.mention} ENTERED THEIR ACTIVATION CODE\U0001F6A8"
            )
            await context.log_action(warning_msg)
            try:
                await modal_interaction.channel.send(warning_msg)
            except Exception:
                pass
            await modal_interaction.response.send_message(
                "Owner authorization accepted.", ephemeral=True
            )
            try:
                await modal_interaction.message.edit(view=self.parent_view)
            except Exception:
                pass

    class XOModal(nextcord.ui.Modal):
        def __init__(self, parent_view: nextcord.ui.View):
            super().__init__(title="XO AUTHORIZATION")
            self.parent_view = parent_view
            self.code = nextcord.ui.TextInput(label="XO code")
            self.add_item(self.code)

        async def callback(self, modal_interaction: nextcord.Interaction):
            if self.code.value.strip() != EPSILON_XO_CODE:
                return await modal_interaction.response.send_message(
                    "Authorization failed.", ephemeral=True
                )
            self.parent_view.xo_confirmed = True
            for child in self.parent_view.children:
                if isinstance(child, nextcord.ui.Button) and child.label == "XO CONFIRM":
                    child.disabled = True
                    break
            warning_msg = (
                f"\U0001F6A8{modal_interaction.user.mention} ENTERED THEIR ACTIVATION CODE\U0001F6A8"
            )
            await context.log_action(warning_msg)
            try:
                await modal_interaction.channel.send(warning_msg)
            except Exception:
                pass
            await modal_interaction.response.send_message(
                "XO authorization accepted.", ephemeral=True
            )
            try:
                await modal_interaction.message.edit(view=self.parent_view)
            except Exception:
                pass

    class FleetModal(nextcord.ui.Modal):
        def __init__(self, parent_view: nextcord.ui.View):
            super().__init__(title="FLEET ADMIRAL AUTHORIZATION")
            self.parent_view = parent_view
            self.code = nextcord.ui.TextInput(label="Fleet Admiral code")
            self.add_item(self.code)

        async def callback(self, modal_interaction: nextcord.Interaction):
            if self.code.value.strip() != EPSILON_FLEET_CODE:
                return await modal_interaction.response.send_message(
                    "Authorization failed.", ephemeral=True
                )
            self.parent_view.fleet_confirmed = True
            for child in self.parent_view.children:
                if isinstance(child, nextcord.ui.Button) and child.label == "FLEET CONFIRM":
                    child.disabled = True
                    break
            warning_msg = (
                f"\U0001F6A8{modal_interaction.user.mention} ENTERED THEIR ACTIVATION CODE\U0001F6A8"
            )
            await context.log_action(warning_msg)
            try:
                await modal_interaction.channel.send(warning_msg)
            except Exception:
                pass
            await modal_interaction.response.send_message(
                "Fleet Admiral authorization accepted.", ephemeral=True
            )
            try:
                await modal_interaction.message.edit(view=self.parent_view)
            except Exception:
                pass

    class FinalApprovalView(nextcord.ui.View):
        def __init__(self, initiator_id: int):
            super().__init__()
            self.initiator_id = initiator_id
            self.owner_confirmed = False
            self.xo_confirmed = False
            self.fleet_confirmed = False

        @nextcord.ui.button(label="OWNER CONFIRM", style=nextcord.ButtonStyle.primary)
        async def owner(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if OWNER_ROLE_ID not in [r.id for r in getattr(button_interaction.user, "roles", [])]:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_modal(OwnerModal(self))

        @nextcord.ui.button(label="XO CONFIRM", style=nextcord.ButtonStyle.primary)
        async def xo(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if XO_ROLE_ID not in [r.id for r in getattr(button_interaction.user, "roles", [])]:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_modal(XOModal(self))

        @nextcord.ui.button(label="FLEET CONFIRM", style=nextcord.ButtonStyle.primary)
        async def fleet(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if FLEET_ADMIRAL_ROLE_ID not in [
                r.id for r in getattr(button_interaction.user, "roles", [])
            ]:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_modal(FleetModal(self))

        @nextcord.ui.button(label="LAUNCH", style=nextcord.ButtonStyle.danger)
        async def launch(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if button_interaction.user.id != self.initiator_id:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            if not (
                self.owner_confirmed
                and self.xo_confirmed
                and self.fleet_confirmed
            ):
                return await button_interaction.response.send_message(
                    "Awaiting all confirmations.", ephemeral=True
                )
            await execute_epsilon_actions(context, button_interaction.guild, classified_role)
            await button_interaction.response.send_message(final_screen)

    class ConfirmModal(nextcord.ui.Modal):
        def __init__(self):
            super().__init__(title="EPSILON CONFIRMATION")
            self.input = nextcord.ui.TextInput(
                label="Type secret launch code"
            )
            self.add_item(self.input)

        async def callback(self, modal_interaction: nextcord.Interaction):
            if modal_interaction.user != interaction.user:
                return await modal_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            if self.input.value.strip() != EPSILON_LAUNCH_CODE:
                return await modal_interaction.response.send_message(
                    "Authorization failed. Protocol aborted."
                )
            view = FinalApprovalView(interaction.user.id)
            await modal_interaction.response.send_message(
                final_screen,
                view=view,
            )

    class SecondView(nextcord.ui.View):
        @nextcord.ui.button(label="CONFIRM", style=nextcord.ButtonStyle.danger)
        async def confirm(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_modal(ConfirmModal())

        @nextcord.ui.button(label="ABORT MISSION", style=nextcord.ButtonStyle.success)
        async def abort(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message("Protocol aborted.")

    class FirstView(nextcord.ui.View):
        @nextcord.ui.button(label=" PROCEED ", style=nextcord.ButtonStyle.danger)
        async def proceed(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message(
                warning_two, view=SecondView()
            )

        @nextcord.ui.button(label="ABORT", style=nextcord.ButtonStyle.success)
        async def abort(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message("Protocol aborted.")

    await interaction.response.send_message(
        warning_one, view=FirstView(), allowed_mentions=nextcord.AllowedMentions(roles=True)
    )


async def omega_directive_command(
    context: SpectreContext, interaction: nextcord.Interaction
) -> None:
    guild = getattr(interaction, "guild", None)
    fallback_id = getattr(guild, "id", 0)
    guild_id = guild_id_from_interaction(interaction) or fallback_id
    cfg = get_server_config(guild_id)
    classified_id = (
        cfg.get("CLASSIFIED_ROLE_ID", CLASSIFIED_ROLE_ID)
        if hasattr(cfg, "get")
        else CLASSIFIED_ROLE_ID
    )
    if not classified_id:
        classified_id = CLASSIFIED_ROLE_ID
    classified_role = interaction.guild.get_role(classified_id)
    if not classified_role:
        return await interaction.response.send_message(
            "Classified Clearance role not found.", ephemeral=True
        )
    if interaction.user.top_role.position < classified_role.position:
        return await interaction.response.send_message(
            " Classified clearance required.", ephemeral=True
        )

    screen_one = (
        "[ARCHIVE: OMEGA DIRECTIVE]\n"
        "System handshake in progress...\n"
        "> Validating Lazarus Key fragments\n"
        "> Checking post-Epsilon conditions\n"
        "> High Command clearance level: Level 5+\n"
        "Status: PENDING"
    )

    screen_two = (
        "[AUTHORIZATION REQUIRED]\n"
        "Insert both Lazarus Key fragments.\n"
        "- Primary Command Authentication: READY\n"
        "- Secondary Oversight Authentication: READY\n\n"
        "Note: System will abort if conditions fail.\n"
        "Continue with activation?"
    )

    final_screen = (
        "[OMEGA SEQUENCE INITIATED]\n"
        "This will begin post-Epsilon restoration procedures.\n"
        "System integrity will remain in Skeleton Mode until complete.\n\n"
        "T-minus 10 minutes to full activation.\n"
        "Abort option available until T-minus 1 minute."
    )

    class OmegaModal(nextcord.ui.Modal):
        def __init__(self):
            super().__init__(title="OMEGA AUTHORIZATION")
            self.fragment_one = nextcord.ui.TextInput(label="Primary Fragment")
            self.fragment_two = nextcord.ui.TextInput(label="Secondary Fragment")
            self.add_item(self.fragment_one)
            self.add_item(self.fragment_two)

        async def callback(self, modal_interaction: nextcord.Interaction):
            if modal_interaction.user != interaction.user:
                return await modal_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            if (
                self.fragment_one.value.strip() != OMEGA_KEY_FRAGMENT_1
                or self.fragment_two.value.strip() != OMEGA_KEY_FRAGMENT_2
            ):
                return await modal_interaction.response.send_message(
                    "Authorization failed.", ephemeral=True
                )
            await execute_omega_actions(context, modal_interaction.guild)
            await modal_interaction.response.send_message(final_screen)

    class SecondView(nextcord.ui.View):
        @nextcord.ui.button(label="ENTER KEYS", style=nextcord.ButtonStyle.danger)
        async def enter(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_modal(OmegaModal())

        @nextcord.ui.button(label="ABORT", style=nextcord.ButtonStyle.success)
        async def abort(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message("Omega directive aborted.")

    class FirstView(nextcord.ui.View):
        @nextcord.ui.button(label="CONTINUE", style=nextcord.ButtonStyle.primary)
        async def continue_btn(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message(screen_two, view=SecondView())

        @nextcord.ui.button(label="ABORT", style=nextcord.ButtonStyle.success)
        async def abort(
            self, button: nextcord.ui.Button, button_interaction: nextcord.Interaction
        ):
            if button_interaction.user != interaction.user:
                return await button_interaction.response.send_message(
                    "Unauthorized interaction.", ephemeral=True
                )
            await button_interaction.response.send_message("Omega directive aborted.")

    await interaction.response.send_message(screen_one, view=FirstView())


def register(context: SpectreContext) -> None:
    bot = context.bot

    @bot.slash_command(
        name="protocol-epsilon",
        description="WARNING ONLY ACTIVATE UNDER GUIDANCE OF FILE EPSILON",
        guild_ids=context.slash_guild_ids,
    )
    async def protocol_epsilon(interaction: nextcord.Interaction) -> None:
        await protocol_epsilon_command(context, interaction)

    @bot.slash_command(
        name="omega-directive",
        description="Only activate in case of [REDACTED]",
        guild_ids=context.slash_guild_ids,
    )
    async def omega_directive(interaction: nextcord.Interaction) -> None:
        await omega_directive_command(context, interaction)


__all__ = [
    "apply_protocol_epsilon",
    "execute_epsilon_actions",
    "execute_omega_actions",
    "protocol_epsilon_command",
    "omega_directive_command",
    "register",
]
