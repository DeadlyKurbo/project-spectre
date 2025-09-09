import asyncio
import nextcord
from nextcord import Embed, ButtonStyle
from nextcord.ui import View, Button

from constants import (
    SECTION_ZERO_CHANNEL_ID,
    CATEGORY_STYLES,
    SECTION_ZERO_ROLE_IDS,
    SECTION_ZERO_ASSIGN_ROLES,
    ARCHIVIST_MENU_TIMEOUT,
)
from utils import list_categories
from views import CategoryMenu
from archivist import EditFileView

SECTION_ZERO_EXTRA_CATEGORIES = [
    "operative_ledger",
    "directive_overrides",
    "redaction_matrix",
    "surveillance_cache",
    "obsidian_vault",
]


def _section_zero_categories() -> list[str]:
    """Return Section Zero-specific categories."""

    return list(SECTION_ZERO_EXTRA_CATEGORIES)

SECTION_ZERO_DESC = (
    '"Knowledge is Control"\n\n'
    "───────────────────────────────\n"
    "[1] Operative Ledger\n"
    "   Status: 🟢 **LIVE**\n"
    "   Incomplete dossiers of Zero Operators & Specters.\n"
    "   Redacted exports shared to GU7 archives.\n\n"
    "[2] Directive Overrides\n"
    "   Status: 🔵 **ACTIVE**\n"
    "   Section Zero-issued directives superseding HICOM orders.\n"
    "   Logged as 'official' in GU7, though altered.\n\n"
    "[3] Redaction Matrix\n"
    "   Status: 🟠 **RUNNING**\n"
    "   Live interface to censor, alter, and erase GU7 files.\n"
    "   Select pages, terms, or entire logs for redaction.\n\n"
    "[4] Surveillance Cache\n"
    "   Status: 🟣 **UPDATING...**\n"
    "   Intercepted comms, backdoor access logs, flagged leaks.\n"
    "   Data filtered before GU7 ever sees it.\n\n"
    "[5] Obsidian Vault\n"
    "   Status: 🔴 **SEALED - BLACK HAND ONLY**\n"
    "   Cold-storage of permanently purged or rewritten files.\n"
    "   Zero trace remains in the public archive.\n\n"
    "───────────────────────────────\n"
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
        enter = Button(label="Enter Archive", style=ButtonStyle.secondary)
        enter.callback = self.open_archive
        self.add_item(enter)

        exec_btn = Button(label="Execute", style=ButtonStyle.secondary)
        exec_btn.callback = self.execute_placeholder
        self.add_item(exec_btn)

        purge = Button(label="Purge", style=ButtonStyle.secondary)
        purge.callback = self.open_purge
        self.add_item(purge)

        manage = Button(label="Manage Menu", style=ButtonStyle.secondary)
        manage.callback = self.open_manage
        self.add_item(manage)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        roles = {r.id for r in getattr(interaction.user, "roles", [])}
        allowed = bool(SECTION_ZERO_ROLE_IDS & roles)
        if not allowed:
            await interaction.response.send_message(
                "Access denied.", ephemeral=True
            )
        return allowed

    async def open_archive(self, interaction: nextcord.Interaction):
        """Prompt user to choose which archive to access."""

        async def open_main_archive(i: nextcord.Interaction):
            embed = Embed(
                title="GU7 ARCHIVE",
                description="Select a category…",
                color=0x000000,
            )
            await i.response.send_message(
                embed=embed,
                view=CategoryMenu(categories=list_categories()),
                ephemeral=True,
            )

        async def open_zero_archive(i: nextcord.Interaction):
            for c in SECTION_ZERO_EXTRA_CATEGORIES:
                CATEGORY_STYLES.setdefault(c, (None, 0x000000))
            embed = Embed(
                title="SECTION ZERO ARCHIVE",
                description="Select a category…",
                color=0x000000,
            )
            await i.response.send_message(
                embed=embed,
                view=CategoryMenu(categories=SECTION_ZERO_EXTRA_CATEGORIES),
                ephemeral=True,
            )

        view = View()
        main_btn = Button(label="GU7 Archive", style=ButtonStyle.secondary)
        main_btn.callback = open_main_archive
        view.add_item(main_btn)

        zero_btn = Button(label="Section Zero Archive", style=ButtonStyle.secondary)
        zero_btn.callback = open_zero_archive
        view.add_item(zero_btn)

        await interaction.response.send_message(
            embed=Embed(
                title="ARCHIVE ACCESS",
                description="Select an archive…",
                color=0x000000,
            ),
            view=view,
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
        view = SectionZeroManageView(interaction.user)
        await interaction.response.send_message(
            embed=Embed(
                title="SECTION ZERO // MANAGE MENU",
                description="Select an action…",
                color=0x000000,
            ),
            view=view,
            ephemeral=True,
        )

    async def close_terminal(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            content="Section Zero control terminal closed.", embed=None, view=None
        )


class SectionZeroManageView(View):
    """Ephemeral management interface for Section Zero archive."""

    def __init__(self, user: nextcord.Member):
        import archivist  # local import to avoid circular dependencies

        for c in SECTION_ZERO_EXTRA_CATEGORIES:
            CATEGORY_STYLES.setdefault(c, (None, 0x000000))

        super().__init__(timeout=ARCHIVIST_MENU_TIMEOUT)
        self._archivist = archivist
        self._orig_cat_func = archivist._categories_for_select

        def _sz_categories(limit: int = 25) -> list[str]:
            return _section_zero_categories()[:limit]

        archivist._categories_for_select = _sz_categories
        self.console = archivist.ArchivistConsoleView(user)
        self.limited = archivist.ArchivistLimitedConsoleView(user)

        btn_upload = Button(label="Upload File", style=ButtonStyle.primary)

        async def open_upload(interaction: nextcord.Interaction):
            await interaction.response.send_message(
                embed=Embed(
                    title="Upload File",
                    description="Step 1: Select category…",
                    color=0x00FFCC,
                ),
                view=archivist.UploadFileView(allowed_roles=SECTION_ZERO_ASSIGN_ROLES),
                ephemeral=True,
            )

        btn_upload.callback = open_upload
        self.add_item(btn_upload)

        btn_remove = Button(label="Delete File", style=ButtonStyle.danger)
        btn_remove.callback = self.console.open_remove
        self.add_item(btn_remove)

        btn_archive = Button(label="Archive File", style=ButtonStyle.secondary)
        btn_archive.callback = self.limited.open_archive
        self.add_item(btn_archive)

        btn_categories = Button(label="Manage Categories", style=ButtonStyle.secondary)
        btn_categories.callback = self.console.open_categories
        self.add_item(btn_categories)

    async def on_timeout(self) -> None:
        self._archivist._categories_for_select = self._orig_cat_func
        await super().on_timeout()

    def stop(self) -> None:  # type: ignore[override]
        self._archivist._categories_for_select = self._orig_cat_func
        super().stop()


__all__ = [
    "SectionZeroControlView",
    "section_zero_embed",
    "SECTION_ZERO_CHANNEL_ID",
    "SECTION_ZERO_ROLE_IDS",
]
