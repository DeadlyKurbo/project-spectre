import os
import json

# —— Paths ——
BASE_DIR = os.path.dirname(__file__)
DOSSIERS_DIR = os.path.join(BASE_DIR, "dossiers")
# Persist file clearances in ``clearance.json``.
#
# The file is deliberately excluded from version control to ensure that any
# permissions granted at runtime remain in place even if the repository is
# updated or redeployed.  Utilities below automatically create the file when
# needed so the bot can remember assignments across restarts without manual
# setup.
CLEARANCE_FILE = os.path.join(BASE_DIR, "clearance.json")

# —— Clearance JSON helpers ——

def _normalise_clearance(data):
    """Return ``data`` with all role IDs coerced to ``int``s."""
    normalised = {}
    for category, items in getattr(data, "items", lambda: [])():
        if not isinstance(items, dict):
            continue
        normalised[category] = {}
        for item, roles in items.items():
            if not isinstance(roles, (list, tuple, set)):
                continue
            cleaned = []
            for r in roles:
                try:
                    cleaned.append(int(r))
                except (TypeError, ValueError):
                    continue
            normalised[category][item] = sorted(set(cleaned))
    return normalised

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
                raw = json.load(f)
            except json.JSONDecodeError:
                return {}
        data = _normalise_clearance(raw)
        if data != raw:
            save_clearance(data)
        return data
    return {}

def save_clearance(data):
    clean = _normalise_clearance(data)
    with open(CLEARANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)

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
    # Combine dossiers present on disk with those already tracked in the
    # clearance file.  ``list_items`` only inspects the filesystem which
    # means categories loaded from ``CLEARANCE_FILE`` would otherwise be
    # ignored when the corresponding dossier files are missing.  This was the
    # case when migrating storage backends where the local files hadn't been
    # synced yet.  By taking the union we ensure that every known item is
    # updated consistently.
    file_items = set(list_items(category))
    stored_items = set(cf.get(category, {}))
    items = file_items | stored_items
    cf.setdefault(category, {})
    validated = [_ensure_int(r) for r in roles]
    for name in items:
        cf[category][name] = list(validated)
    save_clearance(cf)

def reset_category_clearance(category: str):
    """Remove all role assignments for items in ``category``."""
    cf = load_clearance()
    file_items = set(list_items(category))
    stored_items = set(cf.get(category, {}))
    items = file_items | stored_items
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
    if not os.path.isdir(DOSSIERS_DIR):
        return []
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


def create_dossier_with_clearance(
    category: str, item: str, content: str, role_id: int
):
    """Create a dossier file and assign an initial clearance role.

    This helper streamlines onboarding new files by wrapping
    :func:`create_dossier_file` and :func:`grant_file_clearance` into a
    single call.  The created file is saved under ``category``/``item`` and
    ``role_id`` is granted access immediately.

    Parameters
    ----------
    category:
        Target dossier category.
    item:
        Name of the dossier without extension.
    content:
        Raw JSON text or plain string to store in the file.
    role_id:
        Discord role ID to grant access.

    Returns
    -------
    str
        Path to the newly created dossier file.
    """
    path = create_dossier_file(category, item, content)
    grant_file_clearance(category, item, role_id)
    return path


def remove_dossier_file(category: str, item: str):
    """Delete a dossier file and clear any associated roles."""
    folder = os.path.join(DOSSIERS_DIR, category)
    path = os.path.join(folder, f"{item}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    os.remove(path)

    cf = load_clearance()
    if category in cf and item in cf[category]:
        del cf[category][item]
        if not cf[category]:
            del cf[category]
        save_clearance(cf)
    return path
