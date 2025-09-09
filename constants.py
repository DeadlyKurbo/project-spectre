import os

# Discord Tokens & Channels
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
# Public archive menu channel
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID", "1408283176102531113"))
ROSTER_CHANNEL_ID = int(os.getenv("ROSTER_CHANNEL_ID", "1375092910961201162"))

# S3/Storage
ROOT_PREFIX = (os.getenv("S3_ROOT_PREFIX") or "dossiers").strip().strip("/")
# Separate storage root for the Section Zero archive.  Defaults to a different
# folder so files are completely isolated from the main archive.
SECTION_ZERO_ROOT_PREFIX = (
    os.getenv("S3_SECTION_ZERO_ROOT_PREFIX") or "section_zero"
).strip().strip("/")

# Default dossier categories shown in menus and their display labels.
# The order of this list determines how categories appear in the UI.
CATEGORY_ORDER = [
    ("high_command_directives", "High Command Directives"),
    ("personnel", "Personnel"),
    ("fleet", "Fleet"),
    ("missions", "Missions"),
    ("intelligence", "Intelligence"),
    ("active_efforts", "Active Efforts"),
    ("tech_equipment", "Tech & Equipment"),
    ("protocols_contingencies", "Protocols & Contingencies"),
]

# Visual identifiers for dossier categories. Each entry maps the category
# slug to a tuple of (emoji, color).  These are used by the archive menu to
# provide quick at-a-glance recognition of sections.

# Global styling for the archive root interface so it can appear with
# consistent branding alongside specific dossier categories.
ARCHIVE_EMOJI = ""
ARCHIVE_COLOR = 0x00FFCC

CATEGORY_STYLES = {
    # Each dossier category is assigned a unique emoji and embed color so the
    # UI can convey an immediate "emotional" context similar to the existing
    # Personnel and Missions sections.  Keeping these definitions centralized
    # makes it easy to tweak the look and feel without touching the rendering
    # code spread throughout the project.
    "high_command_directives": ("📜", 0xE74C3C),
    # "" (saluting face) caused API errors on some Discord clients; use a
    # widely supported fallback emoji to ensure the menu renders reliably.
    "personnel": ("👥", 0x3498DB),
    "fleet": ("🚀", 0x1ABC9C),
    "missions": ("🎯", 0x2ECC71),
    "intelligence": ("🕵️", 0x9B59B6),
    "active_efforts": ("📌", 0xE67E22),
    "tech_equipment": ("💻", 0xF1C40F),
    "protocols_contingencies": ("⚠️", 0x34495E),
    # Root archive interface
    "archive": (ARCHIVE_EMOJI, ARCHIVE_COLOR),
    # Section Zero exclusive categories
    "operative_ledger": ("📓", 0x228B22),
    "directive_overrides": ("📝", 0x4682B4),
    "redaction_matrix": ("🧰", 0xFF8C00),
    "surveillance_cache": ("📡", 0x6A5ACD),
    "obsidian_vault": ("🔒", 0xB22222),
}

# Security keys
EPSILON_LAUNCH_CODE = os.getenv(
    "EPSILON_LAUNCH_CODE", "EPSILON-NIGHTFALL-88XM-THETA"
)
EPSILON_OWNER_CODE = os.getenv(
    "EPSILON_OWNER_CODE", "EPSILON-DAWN-44QK-ALPHA"
)
EPSILON_XO_CODE = os.getenv(
    "EPSILON_XO_CODE", "EPSILON-MIDNIGHT-72LV-GAMMA"
)
EPSILON_FLEET_CODE = os.getenv(
    "EPSILON_FLEET_CODE", "EPSILON-DUSK-11AB-ZETA"
)
OMEGA_KEY_FRAGMENT_1 = os.getenv("OMEGA_KEY_FRAGMENT_1", "OMEGA-LAZARUS-77XI-PI")
OMEGA_KEY_FRAGMENT_2 = os.getenv(
    "OMEGA_KEY_FRAGMENT_2", "Sigma-Omega-Sigma-Code-Talon-68D"
)
OMEGA_BACKUP_PATH = os.getenv("OMEGA_BACKUP_PATH", "backups/.omega.json")

# OpenAI keys & models
LLM_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_ASSISTANT_ID = os.getenv("LLM_ASSISTANT_ID")  # <-- Belangrijk voor Assistants API

# Role IDs
LEVEL1_ROLE_ID = 1365097430713896992
LEVEL2_ROLE_ID = 1402635734506016861
LEVEL3_ROLE_ID = 1365096533069926460
LEVEL4_ROLE_ID = 1365094103578181765
LEVEL5_ROLE_ID = 1365093753035161712
CLASSIFIED_ROLE_ID = 1365093656859512863

# Section Zero clearance roles
ZERO_OPERATOR_ROLE_ID = 1415066013031993384
SPECTRE_ROLE_ID = 1415066469896814692
INQUISITOR_ROLE_ID = 1415067287810998395  # L3 – Inquisitor, no default Section Zero access
HARBINGER_ROLE_ID = 1415067346653020211
BLACK_HAND_ROLE_ID = 1415066599672643614

SECTION_ZERO_ROLE_IDS = {
    ZERO_OPERATOR_ROLE_ID,
    SPECTRE_ROLE_ID,
    HARBINGER_ROLE_ID,
    BLACK_HAND_ROLE_ID,
}

# Section Zero assignable clearance roles in ascending order
SECTION_ZERO_ASSIGN_ROLES = [
    ZERO_OPERATOR_ROLE_ID,
    SPECTRE_ROLE_ID,
    INQUISITOR_ROLE_ID,
    HARBINGER_ROLE_ID,
    BLACK_HAND_ROLE_ID,
]

OWNER_ROLE_ID = int(os.getenv("OWNER_ROLE_ID", "1365087286785474701"))
XO_ROLE_ID = int(os.getenv("XO_ROLE_ID", "1365087292473086102"))
FLEET_ADMIRAL_ROLE_ID = int(
    os.getenv("FLEET_ADMIRAL_ROLE_ID", "1365087291424510022")
)

ALLOWED_ASSIGN_ROLES = {
    LEVEL1_ROLE_ID, LEVEL2_ROLE_ID, LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID, LEVEL5_ROLE_ID, CLASSIFIED_ROLE_ID
}

# Channels
UPLOAD_CHANNEL_ID = int(os.getenv("UPLOAD_CHANNEL_ID", "1405751160819683348"))
# Dedicated moderator log channel
DEFAULT_LOG_CHANNEL_ID = int(
    os.getenv("DEFAULT_LOG_CHANNEL_ID", "1410124025329488023")
)
LAZARUS_CHANNEL_ID = int(os.getenv("LAZARUS_CHANNEL_ID", "1409578583634214962"))
CLEARANCE_REQUESTS_CHANNEL_ID = int(os.getenv("CLEARANCE_REQUESTS_CHANNEL_ID", "1405751160819683348"))
LEAD_NOTIFICATION_CHANNEL_ID = int(os.getenv("LEAD_NOTIFICATION_CHANNEL_ID", "1402306158492123318"))
REPORT_REPLY_CHANNEL_ID = int(os.getenv("REPORT_REPLY_CHANNEL_ID", "1410124123690111028"))
SECURITY_LOG_CHANNEL_ID = int(os.getenv("SECURITY_LOG_CHANNEL_ID", "1410124025329488023"))
SECTION_ZERO_CHANNEL_ID = int(
    os.getenv("SECTION_ZERO_CHANNEL_ID", "1415063860628558015")
)

# Roles
LEAD_ARCHIVIST_ROLE_ID = int(os.getenv("LEAD_ARCHIVIST_ROLE_ID", "1405932476089765949"))
ARCHIVIST_ROLE_ID = int(os.getenv("ARCHIVIST_ROLE_ID", "1405757611919544360"))
TRAINEE_ROLE_ID = int(os.getenv("TRAINEE_ROLE_ID", "1409400366440906782"))
HIGH_COMMAND_ROLE_ID = int(os.getenv("HIGH_COMMAND_ROLE_ID", "1405932476089765951"))

# Personnel rank roles
CAPTAIN_ROLE_ID = int(os.getenv("CAPTAIN_ROLE_ID", "1365087305085223084"))
VETERAN_OFFICER_ROLE_ID = int(os.getenv("VETERAN_OFFICER_ROLE_ID", "1402032805453627412"))
OFFICER_ROLE_ID = int(os.getenv("OFFICER_ROLE_ID", "1365087307551740019"))
SPECIALIST_ROLE_ID = int(os.getenv("SPECIALIST_ROLE_ID", "1402033076967837768"))
SEAMAN_ROLE_ID = int(os.getenv("SEAMAN_ROLE_ID", "1365087308642127994"))
TRAINEE_RANK_ROLE_ID = int(os.getenv("TRAINEE_RANK_ROLE_ID", "1402033315892039711"))

# Timeouts & Limits
ARCHIVIST_MENU_TIMEOUT = 5 * 60  # 5 min
CONTENT_MAX_LENGTH = 500
PAGE_SEPARATOR = "\f"

# UI Text
INTRO_TITLE = "Project SPECTRE File Explorer"
INTRO_DESC = (
    "Welcome, Operative.\n"
    "Use the menus below to browse files. Actions are monitored. Do remember some files need to be opened in google documents for full access.\n\n"
    "**Archivist Console** (ephemeral): `/archivist`\n"
    "• Upload / Remove files\n"
    "• Grant / Revoke file clearances\n\n"
    "**Files**: `.json` or `.txt`"
)

REG_ARCHIVIST_TITLE = " SPECTRE // Archivist Node [Restricted]"
REG_ARCHIVIST_DESC = (
    '> "Operator authentication verified."\n'
    '> Mode: RESTRICTED • Write-capable (scoped)\n\n'
    "You are connected to the Glacier Unit 7 archive with limited privileges.\n\n"
    "• Upload new dossiers to the repository\n"
    "• Remove outdated files — rate limited to prevent data churn\n"
    "• All actions are signed to your Operator ID and audited\n\n"
    "Status\n"
    "• Deletes: LIMITED (per-hour quota)\n"
    "• Edits: LIMITED (raw only, 6 per hour)\n"
    "• Clearance tools: LOCKED (insufficient authority)"
)

LEAD_ARCHIVIST_TITLE = " SPECTRE // Command Authority Interface (L5)"
LEAD_ARCHIVIST_DESC = (
    '> "Glacier Command override detected."\n'
    '> Clearance Tier: L5+ • Authority: Full Admin\n\n'
    "You hold administrative control over the SPECTRE archive.\n"
    "Actions executed here are definitive and propagate fleet-wide.\n\n"
    "Capabilities\n"
    "• Dossier lifecycle: upload • edit • remove\n"
    "• Access control: grant/revoke file-level clearances\n"
    "• Systems: integrity scan • backup/restore • build controls"
)

HIGH_COMMAND_TITLE = " SPECTRE // High Command Terminal"
HIGH_COMMAND_DESC = (
    '> "Executive override confirmed."\n'
    '> Clearance Tier: HC • Authority: Total\n\n'
    "You wield ultimate control over the SPECTRE archive.\n\n"
    "Capabilities\n"
    "• All Lead Archivist functions\n"
    "• Member management: ban • kick • timeout\n"
    "• Archive lockdown controls"
)

TRAINEE_ARCHIVIST_TITLE = "[ACCESS NODE: TRAINING SANDBOX]"
TRAINEE_ARCHIVIST_DESC = (
    "Welcome, Operator.\n"
    "All changes made here remain in *Pending* status until reviewed by a Lead-Archivist.\n\n"
    "Capabilities\n"
    "• Perform real archive actions in a sandbox\n"
    "• Submit changes for Lead review\n"
    "• Receive feedback & resubmit if needed"
)
