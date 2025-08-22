import os, json
from dotenv import load_dotenv
load_dotenv()

# ==== ENV ====
TOKEN               = os.getenv("DISCORD_TOKEN")
GUILD_ID            = int(os.getenv("GUILD_ID", "0"))  # zet dit in Railway!
MENU_CHANNEL_ID     = int(os.getenv("MENU_CHANNEL_ID", "0"))
UPLOAD_CHANNEL_ID   = int(os.getenv("UPLOAD_CHANNEL_ID", "0"))
LEAD_ARCHIVIST_MENU_CHANNEL_ID = int(os.getenv("LEAD_ARCHIVIST_MENU_CHANNEL_ID", "0"))
ARCHIVIST_MENU_CHANNEL_ID      = int(os.getenv("ARCHIVIST_MENU_CHANNEL_ID", "0"))
ROOT_PREFIX         = (os.getenv("S3_ROOT_PREFIX") or "dossiers").strip().strip("/")

# ==== UI copy ====
INTRO_TITLE = "Project SPECTRE — Black Archives"
INTRO_DESC  = (
    "Unseal dossiers, search the vault, and command the clandestine console.\n"
    "Only Lead Archivists may rewrite clearance and trigger shadow backups."
)

# ==== Archivist roles (hardcoded zoals gevraagd) ====
LEAD_ARCHIVIST_ROLE_ID = 1405932476089765949  # alles mag
ARCHIVIST_ROLE_ID      = 1405757611919544360  # beperkt
ARCHIVIST_MONITOR_CHANNEL_ID = 1402306158492123318  # hier laten we archivists werken

# ==== Logging ====
_LOG_ENV = os.getenv("LOG_CHANNEL_ID")
DEFAULT_LOG_CHANNEL_ID = int(_LOG_ENV) if _LOG_ENV else None
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "log_channel.json")

# ==== Backups ====
BACKUP_DIR           = f"{ROOT_PREFIX}/_backups".replace("//", "/")
BACKUP_INTERVAL_MIN  = int(os.getenv("BACKUP_INTERVAL_MIN", "60"))  # hourly default

# ==== Mission scheduler ====
MISSION_CHANNEL_ID   = int(os.getenv("MISSION_CHANNEL_ID", "0"))

# ==== Clearance levels (optioneel gebruikt voor fallback "clearance": N in JSON) ====
# Voeg je eigen role->level mapping toe; niet kritisch voor ACL-rollen hierboven
ROLE_LEVELS = {
    # voorbeeld:
    # 123456789012345678: 1,
    # 223456789012345678: 2,
    # ...
}

# ==== Toestane rollen om als file-clearance te geven via upload/grant ====
ALLOWED_ASSIGN_ROLES = [
    ARCHIVIST_ROLE_ID,
    LEAD_ARCHIVIST_ROLE_ID,
]

# ==== State helpers (log channel onthouden indien nodig) ====

def _read_state():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

def _write_state(st: dict):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_log_channel():
    st = _read_state()
    return st.get("log_channel_id") if st.get("log_channel_id") is not None else DEFAULT_LOG_CHANNEL_ID

def set_log_channel(cid: int):
    st = _read_state()
    st["log_channel_id"] = int(cid)
    _write_state(st)
