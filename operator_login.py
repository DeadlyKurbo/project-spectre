import random
import string
import time
import hashlib
from dataclasses import dataclass, asdict
from typing import Dict

from storage_spaces import read_json, save_json

from constants import (
    LEVEL1_ROLE_ID,
    LEVEL2_ROLE_ID,
    LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID,
    LEVEL5_ROLE_ID,
    CLASSIFIED_ROLE_ID,
    ROOT_PREFIX,
    CAPTAIN_ROLE_ID,
    VETERAN_OFFICER_ROLE_ID,
    OFFICER_ROLE_ID,
    SPECIALIST_ROLE_ID,
    SEAMAN_ROLE_ID,
    TRAINEE_RANK_ROLE_ID,
)


@dataclass
class OperatorRecord:
    user_id: int
    id_code: str
    password_hash: str | None = None
    clearance: int = 1
    failed_attempts: int = 0
    locked_until: float = 0.0


_operators: Dict[int, OperatorRecord] = {}


_OPERATORS_FILE = f"{ROOT_PREFIX}/operators.json"


def _load() -> None:
    try:
        data = read_json(_OPERATORS_FILE)
    except Exception:
        return
    for uid, info in data.items():
        try:
            _operators[int(uid)] = OperatorRecord(**info)
        except Exception:
            continue


def _save() -> None:
    data = {str(uid): asdict(op) for uid, op in _operators.items()}
    save_json(_OPERATORS_FILE, data)


_load()


def _generate_id() -> str:
    """Return a pseudo-random digital operator ID."""
    block2 = f"{random.randint(0, 9999):04d}"
    block3 = "".join(random.choices(string.ascii_uppercase + string.digits, k=2))
    return f"GU7-OPR-{block2}-{block3}"


def list_operators() -> list[OperatorRecord]:
    """Return a list of all known operator records."""
    return list(_operators.values())


def update_id_code(user_id: int, new_id: str | None) -> None:
    """Update the ID code for ``user_id``.

    ``new_id`` is coerced to ``str`` and silently ignored if ``None`` or
    blank.  Previously passing ``None`` would raise an ``AttributeError`` when
    attempting to call :py:meth:`str.strip` on it.
    """
    op = _operators.get(user_id)
    if not op:
        return
    if not new_id:
        return
    op.id_code = str(new_id).strip()
    _save()


def delete_operator(user_id: int) -> None:
    """Remove the operator record for ``user_id`` if present."""
    if user_id in _operators:
        del _operators[user_id]
        _save()


def get_or_create_operator(user_id: int) -> OperatorRecord:
    """Return existing operator record or create a new one."""
    op = _operators.get(user_id)
    if op is None:
        op = OperatorRecord(user_id=user_id, id_code=_generate_id())
        _operators[user_id] = op
        _save()
    return op


def set_password(user_id: int, password: str) -> None:
    op = get_or_create_operator(user_id)
    op.password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    op.failed_attempts = 0
    op.locked_until = 0.0
    _save()


def verify_password(user_id: int, password: str) -> tuple[bool, bool]:
    """Return (success, locked) after verifying ``password``."""
    op = get_or_create_operator(user_id)
    now = time.time()
    if op.locked_until and now < op.locked_until:
        return False, True
    if op.password_hash and hashlib.sha256(password.encode("utf-8")).hexdigest() == op.password_hash:
        op.failed_attempts = 0
        op.locked_until = 0.0
        _save()
        return True, False
    op.failed_attempts += 1
    if op.failed_attempts >= 3:
        op.locked_until = now + 300  # 5 minutes lockout
    _save()
    return False, False


def set_clearance(user_id: int, level: int) -> None:
    get_or_create_operator(user_id).clearance = int(level)
    _save()


def has_classified_clearance(member) -> bool:
    """Return ``True`` if ``member`` possesses the Classified role.

    The check is performed directly against :data:`CLASSIFIED_ROLE_ID` so that
    callers can reliably detect Classified operatives without relying on
    :func:`detect_clearance`'s return value.  This guards against situations
    where ``detect_clearance`` might fail (for example if role objects use
    unexpected types for their ``id`` attribute).
    """

    roles = getattr(member, "roles", [])
    return any(getattr(r, "id", 0) == CLASSIFIED_ROLE_ID for r in roles)


def detect_rank(member) -> str:
    """Return rank name for ``member`` based on role IDs."""

    if has_classified_clearance(member):
        return "High Command"

    roles = getattr(member, "roles", [])
    mapping = [
        (CAPTAIN_ROLE_ID, "Captain"),
        (VETERAN_OFFICER_ROLE_ID, "Veteran Officer"),
        (OFFICER_ROLE_ID, "Officer"),
        (SPECIALIST_ROLE_ID, "Specialist"),
        (SEAMAN_ROLE_ID, "Seaman"),
        (TRAINEE_RANK_ROLE_ID, "Trainee"),
    ]
    for role_id, name in mapping:
        if any(getattr(r, "id", 0) == role_id for r in roles):
            return name
    return "Trainee"


def detect_clearance(member) -> int:
    """Return numeric clearance level for ``member`` based on roles."""
    if has_classified_clearance(member):
        return 6

    roles = getattr(member, "roles", [])
    mapping = [
        (LEVEL5_ROLE_ID, 5),
        (LEVEL4_ROLE_ID, 4),
        (LEVEL3_ROLE_ID, 3),
        (LEVEL2_ROLE_ID, 2),
        (LEVEL1_ROLE_ID, 1),
    ]
    for role_id, level in mapping:
        if any(getattr(r, "id", 0) == role_id for r in roles):
            return level
    rank_mapping = [
        (CAPTAIN_ROLE_ID, 5),
        (VETERAN_OFFICER_ROLE_ID, 4),
        (OFFICER_ROLE_ID, 3),
        (SPECIALIST_ROLE_ID, 3),
        (SEAMAN_ROLE_ID, 2),
        (TRAINEE_RANK_ROLE_ID, 1),
    ]
    for role_id, level in rank_mapping:
        if any(getattr(r, "id", 0) == role_id for r in roles):
            return level
    return 1


def get_allowed_categories(level: int, categories: list[str]) -> list[str]:
    """Return subset of ``categories`` allowed for given ``level``.

    Operators with ``CLASSIFIED`` clearance (level ``6`` and above) should be
    able to access any existing dossier category.  Previously the function only
    returned categories from a predefined allow-list which meant newly created
    categories were hidden even from classified operators.  To avoid that, when
    the level is ``6`` or higher we simply return ``categories`` unchanged.
    """

    level = int(level)
    if level >= 6:
        # Classified operators have unrestricted access; preserve order.
        return list(categories)

    allowed: set[str] = set()
    if level >= 1:
        allowed.update({"missions", "personnel"})
    if level >= 2:
        allowed.add("intel")
    if level >= 3:
        allowed.add("fleet")
    if level >= 4:
        allowed.update({"tech_equipment", "active_efforts"})
    if level >= 5:
        allowed.update({"high_command_directives", "protocols_contingencies"})
    # levels above simply inherit from previous
    return [c for c in categories if c in allowed]


def generate_session_id() -> str:
    return "SES-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
