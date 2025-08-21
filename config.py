import os
from dotenv import load_dotenv

load_dotenv()

# ==== ENV / CONST ====
TOKEN           = os.getenv("DISCORD_TOKEN")
GUILD_ID        = int(os.getenv("GUILD_ID", "0"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID", "1402017286432227449"))
ROOT_PREFIX     = (os.getenv("S3_ROOT_PREFIX") or "dossiers").strip().strip("/")

# Roles (pas aan naar wens)
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

INTRO_TITLE = "Project SPECTRE File Explorer"
INTRO_DESC  = (
    "Welcome, Operative.\n"
    "Use the menus below to browse files. Actions are monitored. Do remember some files need to be opened in google documents for full access.\n\n"
    "**Archivist Console** (ephemeral): `/archivist`\n"
    "• Upload / Remove files\n"
    "• Grant / Revoke file clearances\n\n"
    "**Files**: `.json` or `.txt`"
)

# --- simple persistent state for log channel ---
_STATE_PATH = os.path.join(os.path.dirname(__file__), "bot_state.json")

def _read_state():
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

def _write_state(st):
    try:
        with open(_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_log_channel():
    st = _read_state()
    return st.get("log_channel_id", DEFAULT_LOG_CHANNEL_ID)

def set_log_channel(cid: int):
    st = _read_state()
    st["log_channel_id"] = int(cid)
    _write_state(st)
