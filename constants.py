import os
from dotenv import load_dotenv

load_dotenv()

TOKEN           = os.getenv("DISCORD_TOKEN")
GUILD_ID        = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID", "1402017286432227449"))
ROOT_PREFIX     = (os.getenv("S3_ROOT_PREFIX") or "dossiers").strip().strip("/")

LEVEL1_ROLE_ID     = 1365097430713896992
LEVEL2_ROLE_ID     = 1402635734506016861
LEVEL3_ROLE_ID     = 1365096533069926460
LEVEL4_ROLE_ID     = 1365094103578181765
LEVEL5_ROLE_ID     = 1365093753035161712
CLASSIFIED_ROLE_ID = 1365093656859512863

ALLOWED_ASSIGN_ROLES = {
    LEVEL1_ROLE_ID, LEVEL2_ROLE_ID, LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID, LEVEL5_ROLE_ID, CLASSIFIED_ROLE_ID
}

UPLOAD_CHANNEL_ID      = 1405751160819683348
DEFAULT_LOG_CHANNEL_ID = 1402306158492123318
# Channel where clearance requests are sent by default.
CLEARANCE_REQUESTS_CHANNEL_ID = int(
    os.getenv("CLEARANCE_REQUESTS_CHANNEL_ID", "1405751160819683348")
)
# Role to ping when a clearance request is made.
LEAD_ARCHIVIST_ROLE_ID = int(
    os.getenv("LEAD_ARCHIVIST_ROLE_ID", "1405932476089765949")
)

INTRO_TITLE = "Project SPECTRE File Explorer"
INTRO_DESC  = (
    "Welcome, Operative.\n"
    "Use the menus below to browse files. Actions are monitored. Do remember some files need to be opened in google documents for full access.\n\n"
    "**Archivist Console** (ephemeral): `/archivist`\n"
    "• Upload / Remove files\n"
    "• Grant / Revoke file clearances\n\n"
    "**Files**: `.json` or `.txt`"
)
