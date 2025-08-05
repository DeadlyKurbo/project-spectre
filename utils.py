import os
import json

# —— Paths ——
BASE_DIR = os.path.dirname(__file__)
DOSSIERS_DIR = os.path.join(BASE_DIR, "dossiers")
CLEARANCE_FILE = os.path.join(BASE_DIR, "clearance.json")
LOG_CHANNEL_FILE = os.path.join(BASE_DIR, "log_channel.json")

# —— Clearance JSON helpers ——
def load_clearance():
    with open(CLEARANCE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_clearance(data):
    with open(CLEARANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_required_roles(category: str, item: str):
    cf = load_clearance()
    return set(cf.get(category, {}).get(item, []))

def set_category_clearance(category: str, roles):
    """Apply the same role list to every item within ``category``."""
    cf = load_clearance()
    items = list_items(category)
    cf.setdefault(category, {})
    for name in items:
        cf[category][name] = list(roles)
    save_clearance(cf)

def reset_category_clearance(category: str):
    """Remove all role assignments for items in ``category``."""
    cf = load_clearance()
    items = list_items(category)
    cf.setdefault(category, {})
    for name in items:
        cf[category][name] = []
    save_clearance(cf)

# —— Log channel helpers ——
def load_log_channel():
    if os.path.exists(LOG_CHANNEL_FILE):
        with open(LOG_CHANNEL_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                return None
            return data.get("channel_id")
    return None

def save_log_channel(channel_id: int):
    with open(LOG_CHANNEL_FILE, "w", encoding="utf-8") as f:
        json.dump({"channel_id": channel_id}, f)

# —— File listing helpers ——
def list_categories():
    return [
        d for d in os.listdir(DOSSIERS_DIR)
        if os.path.isdir(os.path.join(DOSSIERS_DIR, d))
    ]

def list_items(category: str):
    folder = os.path.join(DOSSIERS_DIR, category)
    if not os.path.isdir(folder):
        return []
    return [f[:-5] for f in os.listdir(folder) if f.lower().endswith(".json")]

# —— Dossier creation helper ——
def create_dossier_file(category: str, item: str, content: str):
    """Create a new dossier JSON file from ``content``."""
    folder = os.path.join(DOSSIERS_DIR, category)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{item}.json")
    if os.path.exists(path):
        raise FileExistsError(path)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {"content": content}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path
