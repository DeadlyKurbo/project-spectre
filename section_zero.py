import asyncio
import nextcord
from nextcord import Embed, ButtonStyle
from nextcord.ui import View, Button

from constants import (
    CLASSIFIED_ROLE_ID,
    SECTION_ZERO_CHANNEL_ID,
    CATEGORY_STYLES,
)
from utils import list_categories
from views import CategoryMenu
from archivist import EditFileView

SECTION_ZERO_EXTRA_CATEGORIES = [
    "operative_ledger",
    "directive_overrides",
    "redaction_matrix",
    "surveillance_cache",
    "obelisk_node",
]

SECTION_ZERO_DESC = (
    "[1] Operative Ledger      (LIVE)\n"
    "[2] Directive Overrides   (ACTIVE)\n"
    "[3] Redaction Matrix      (RUNNING)\n"
    "[4] Surveillance Cache    (UPDATING...)\n"
    "[5] Obelisk Node          (LOCKED - BLACK HAND ONLY)\n\n"
    ">> Select Control Node <<"
)


def section_zero_embed() -> Embed:
    return Embed(
        title="\u26ab SECTION ZERO // CONTROL TERMINAL ACTIVE",
        description=SECTION_ZERO_DESC,
        color=0x000000,
    )


class SectionZeroControlView(View):
    """Control menu for Section Zero archive."""

    def __init__(self):
        try:
            asyncio.get_running_loop()
            super().__init__(timeout=None)
            self._setup_buttons()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_init())

    async def _async_init(self):
        super().__init__(timeout=None)
        self._setup_buttons()

    def _setup_buttons(self):
        enter = Button(label="Enter Archive", style=ButtonStyle.primary)
        enter.callback = self.open_archive
        self.add_item(enter)

        exec_btn = Button(label="Execute", style=ButtonStyle.secondary)
        exec_btn.callback = self.execute_placeholder
        self.add_item(exec_btn)

        purge = Button(label="Purge", style=ButtonStyle.danger)
        purge.callback = self.open_purge
        self.add_item(purge)

        ret = Button(label="Return", style=ButtonStyle.secondary)
        ret.callback = self.close_terminal
        self.add_item(ret)

        manage = Button(label="Manage Menu", style=ButtonStyle.primary)
        manage.callback = self.open_manage
        self.add_item(manage)

    async def open_archive(self, interaction: nextcord.Interaction):
        cats = list_categories() + SECTION_ZERO_EXTRA_CATEGORIES
        # ensure styles exist for extra categories
        for c in SECTION_ZERO_EXTRA_CATEGORIES:
            CATEGORY_STYLES.setdefault(c, (None, 0x000000))
        embed = Embed(
            title="SECTION ZERO ARCHIVE",
            description="Select a category…",
            color=0x000000,
        )
        await interaction.response.send_message(
            embed=embed,
            view=CategoryMenu(categories=cats),
            ephemeral=True,
        )

    async def execute_placeholder(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            " Execute function not yet implemented.", ephemeral=True
        )

    async def open_purge(self, interaction: nextcord.Interaction):
        view = EditFileView(interaction.user)
        await interaction.response.send_message(
            embed=Embed(
                title="SECTION ZERO // PURGE",
                description="Select a category and file to redact.",
                color=0x000000,
            ),
            view=view,
            ephemeral=True,
        )

    async def open_manage(self, interaction: nextcord.Interaction):
        view = View()
        btn = Button(label="Return", style=ButtonStyle.secondary)
        btn.callback = self._return_to_main
        view.add_item(btn)
        await interaction.response.edit_message(
            embed=Embed(
                title="SECTION ZERO // MANAGE MENU",
                description="Management interface pending implementation.",
                color=0x000000,
            ),
            view=view,
        )

    async def _return_to_main(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=section_zero_embed(), view=SectionZeroControlView()
        )

    async def close_terminal(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            content="Section Zero control terminal closed.", embed=None, view=None
        )


__all__ = [
    "SectionZeroControlView",
    "section_zero_embed",
    "SECTION_ZERO_CHANNEL_ID",
    "CLASSIFIED_ROLE_ID",
]
