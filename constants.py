import os
from dotenv import load_dotenv

load_dotenv()

TOKEN           = os.getenv("DISCORD_TOKEN")
GUILD_ID        = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID", "1402017286432227449"))
ROSTER_CHANNEL_ID = int(os.getenv("ROSTER_CHANNEL_ID", "1375092910961201162"))
ROOT_PREFIX     = (os.getenv("S3_ROOT_PREFIX") or "dossiers").strip().strip("/")
EPSILON_LAUNCH_CODE = os.getenv(
    "EPSILON_LAUNCH_CODE", "EPSILON-NIGHTFALL-88XM-THETA"
)
OMEGA_KEY_FRAGMENT_1 = os.getenv(
    "OMEGA_KEY_FRAGMENT_1", "OMEGA-LAZARUS-77XI-PI"
)
OMEGA_KEY_FRAGMENT_2 = os.getenv(
    "OMEGA_KEY_FRAGMENT_2", "Sigma-Omega-Sigma-Code-Talon-68D"
)
OMEGA_BACKUP_PATH = os.getenv("OMEGA_BACKUP_PATH", "backups/.omega.json")

# OpenAI key, model and assistant for optional LLM features
LLM_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")

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
DEFAULT_LOG_CHANNEL_ID = 1408283176102531113
# Channel used by Lazarus for status reports.
LAZARUS_CHANNEL_ID = int(os.getenv("LAZARUS_CHANNEL_ID", "1409578583634214962"))
# Channel where clearance requests are sent by default.
CLEARANCE_REQUESTS_CHANNEL_ID = int(
    os.getenv("CLEARANCE_REQUESTS_CHANNEL_ID", "1405751160819683348")
)
# Channel where archivist archive/edit requests are sent.
LEAD_NOTIFICATION_CHANNEL_ID = int(
    os.getenv("LEAD_NOTIFICATION_CHANNEL_ID", "1402306158492123318")
)
# Channel where reporter replies and acknowledgements are logged.
REPORT_REPLY_CHANNEL_ID = int(
    os.getenv("REPORT_REPLY_CHANNEL_ID", "1402306158492123318")
)
# Channel where access denial incidents are logged.
SECURITY_LOG_CHANNEL_ID = int(
    os.getenv("SECURITY_LOG_CHANNEL_ID", "1402306158492123318")
)
# Role to ping when a clearance request is made.
LEAD_ARCHIVIST_ROLE_ID = int(
    os.getenv("LEAD_ARCHIVIST_ROLE_ID", "1405932476089765949")
)
# Role ID for regular Archivists.
ARCHIVIST_ROLE_ID = int(
    os.getenv("ARCHIVIST_ROLE_ID", "1405757611919544360")
)

# Role ID for Archivist Trainees.
TRAINEE_ROLE_ID = int(
    os.getenv("TRAINEE_ROLE_ID", "1409400366440906782")
)

# How long the Archivist console menus remain active (seconds).
ARCHIVIST_MENU_TIMEOUT = 5 * 60

# Maximum allowed characters for content fields.
CONTENT_MAX_LENGTH = 500

# Separator used between pages in multi-page uploads.
PAGE_SEPARATOR = "\f"

INTRO_TITLE = "Project SPECTRE File Explorer"
INTRO_DESC  = (
    "Welcome, Operative.\n"
    "Use the menus below to browse files. Actions are monitored. Do remember some files need to be opened in google documents for full access.\n\n"
    "**Archivist Console** (ephemeral): `/archivist`\n"
    "• Upload / Remove files\n"
    "• Grant / Revoke file clearances\n\n"
    "**Files**: `.json` or `.txt`"
)

REG_ARCHIVIST_TITLE = "🗄️ SPECTRE // Archivist Node [Restricted]"
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

LEAD_ARCHIVIST_TITLE = "🔒 SPECTRE // Command Authority Interface (L5)"
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

TRAINEE_ARCHIVIST_TITLE = "[ACCESS NODE: TRAINING SANDBOX]"
TRAINEE_ARCHIVIST_DESC = (
    "Welcome, Operator.\n"
    "All changes made here remain in *Pending* status until reviewed by a Lead-Archivist.\n\n"
    "Capabilities\n"
    "• Perform real archive actions in a sandbox\n"
    "• Submit changes for Lead review\n"
    "• Receive feedback & resubmit if needed"
)
