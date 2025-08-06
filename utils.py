import os
import json

# —— Paths ——
BASE_DIR = os.path.dirname(__file__)
DOSSIERS_DIR = os.path.join(BASE_DIR, "dossiers")
# Allow deployments to store mutable state outside the repository by setting
# ``SPECTRE_DATA_DIR`` to a writable directory. Falling back to ``BASE_DIR``
# preserves existing behaviour for simple installs.
DATA_DIR = os.environ.get("SPECTRE_DATA_DIR", BASE_DIR)
# Persist file clearances in ``clearance.json`` within ``DATA_DIR``.
#
# The file is deliberately excluded from version control so any permissions
# granted at runtime survive code updates and redeploys. The helpers below
# create it as needed so the bot can remember assignments without manual
# setup.
CLEARANCE_FILE = os.path.join(DATA_DIR, "clearance.json")

# —— Clearance JSON helpers ——
def load_clearance():
    """Return the current clearance mapping.

    The original implementation assumed that ``CLEARANCE_FILE`` already
    existed and contained valid JSON.  In practice the bot may run for the
    first time on a fresh system or the file could become corrupted.  In those
    cases the helper would raise ``FileNotFoundError`` or
    ``json.JSONDecodeError`` which prevented commands such as
    ``/grantfileclearance`` or ``/revokefileclearance`` from persisting their
    changes.  To make these operations robust we fall back to an empty
    dictionary whenever the file cannot be read.
    """
    if os.path.exists(CLEARANCE_FILE):
        with open(CLEARANCE_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_clearance(data):
    os.makedirs(os.path.dirname(CLEARANCE_FILE), exist_ok=True)
    with open(CLEARANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def _ensure_int(value: int) -> int:
    """Return ``value`` as an ``int``.

    Raises
    ------
    TypeError
        If ``value`` cannot be interpreted as an integer.
    """
    try:
        return int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise TypeError("value must be an integer") from exc


def get_required_roles(category: str, item: str):
    cf = load_clearance()
    return {int(r) for r in cf.get(category, {}).get(item, [])}

def grant_file_clearance(category: str, item: str, role_id: int):
    """Grant ``role_id`` access to a dossier and persist the change."""
    role_id = _ensure_int(role_id)
    cf = load_clearance()
    cf.setdefault(category, {})
    cf[category].setdefault(item, [])
    if role_id not in cf[category][item]:
        cf[category][item].append(role_id)
        save_clearance(cf)

def revoke_file_clearance(category: str, item: str, role_id: int):
    """Revoke ``role_id`` access from a dossier and persist the change."""
    role_id = _ensure_int(role_id)
    cf = load_clearance()
    roles = cf.get(category, {}).get(item, [])
    if role_id in roles:
        roles.remove(role_id)
        save_clearance(cf)

def set_category_clearance(category: str, roles):
    """Apply the same role list to every item within ``category``."""
    cf = load_clearance()
    items = list_items(category)
    cf.setdefault(category, {})
    validated = [_ensure_int(r) for r in roles]
    for name in items:
        cf[category][name] = list(validated)
    save_clearance(cf)

def reset_category_clearance(category: str):
    """Remove all role assignments for items in ``category``."""
    cf = load_clearance()
    items = list_items(category)
    cf.setdefault(category, {})
    for name in items:
        cf[category][name] = []
    save_clearance(cf)


def set_files_clearance(mapping, roles):
    """Apply the same role list to selected items across categories."""
    cf = load_clearance()
    validated = [_ensure_int(r) for r in roles]
    for category, items in mapping.items():
        cf.setdefault(category, {})
        for name in items:
            cf[category][name] = list(validated)
    save_clearance(cf)


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
