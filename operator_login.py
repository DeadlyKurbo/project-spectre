import random
import string
import time
import hashlib
import logging
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
from server_config import get_roles_for_level


@dataclass
class OperatorRecord:
    user_id: int
    id_code: str
    account_name: str = ""
    password_hash: str | None = None
    clearance: int = 1
    failed_attempts: int = 0
    locked_until: float = 0.0
    name: str = ""
    age: int | None = None
    specialties: str = ""
    occupation: str = ""


# Timestamp of last successful authentication per operator (ephemeral)
_login_times: Dict[int, float] = {}


# Session validity duration in seconds (30 minutes)
_SESSION_TTL = 30 * 60


_operators: Dict[int, OperatorRecord] = {}
logger = logging.getLogger("spectre.clearance")


_OPERATORS_FILE = f"{ROOT_PREFIX}/operators.json"


def _guild_id_from_member(member) -> int | None:
    guild = getattr(member, "guild", None)
    gid = getattr(guild, "id", None)
    if gid is not None:
        return gid
    return getattr(member, "guild_id", None)


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
    return f"SPT-OPR-{block2}-{block3}"


def list_operators() -> list[OperatorRecord]:
    """Return a list of all known operator records."""
    return list(_operators.values())


def _normalize_account_name(account_name: str | None) -> str:
    if not account_name:
        return ""
    return str(account_name).strip().lower()


def account_name_in_use(account_name: str | None, *, exclude_user_id: int | None = None) -> bool:
    normalized = _normalize_account_name(account_name)
    if not normalized:
        return False
    for operator in _operators.values():
        if exclude_user_id is not None and operator.user_id == exclude_user_id:
            continue
        if _normalize_account_name(operator.account_name) == normalized:
            return True
    return False


def get_operator_by_account_name(account_name: str | None) -> OperatorRecord | None:
    normalized = _normalize_account_name(account_name)
    if not normalized:
        return None
    for operator in _operators.values():
        if _normalize_account_name(operator.account_name) == normalized:
            return operator
    return None


def get_operator_by_account_identifier(identifier: str | None) -> OperatorRecord | None:
    normalized = _normalize_account_name(identifier)
    if not normalized:
        return None
    id_normalized = str(identifier).strip().lower()
    for operator in _operators.values():
        if _normalize_account_name(operator.account_name) == normalized:
            return operator
        if operator.id_code and operator.id_code.strip().lower() == id_normalized:
            return operator
    return None


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


def set_account_name(user_id: int, account_name: str | None) -> None:
    op = _operators.get(user_id)
    if not op:
        return
    cleaned = str(account_name or "").strip()
    if not cleaned:
        return
    op.account_name = cleaned
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
        _login_times[user_id] = now
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


def update_profile(
    user_id: int,
    *,
    name: str | None = None,
    age: int | None = None,
    specialties: str | None = None,
    occupation: str | None = None,
) -> None:
    """Update stored profile metadata for ``user_id``."""

    op = get_or_create_operator(user_id)
    if name is not None:
        op.name = name.strip()
    if age is not None:
        op.age = int(age)
    if specialties is not None:
        op.specialties = specialties.strip()
    if occupation is not None:
        op.occupation = occupation.strip()
    _save()


def has_active_session(user_id: int) -> bool:
    """Return ``True`` if ``user_id`` authenticated within the last 30 minutes."""
    now = time.time()
    last = _login_times.get(user_id, 0)
    return bool(last) and now - last < _SESSION_TTL


def touch_session(user_id: int) -> None:
    """Refresh session timestamp for ``user_id`` to extend validity."""
    _login_times[user_id] = time.time()


def has_classified_clearance(member, guild_id: int | None = None) -> bool:
    """Return ``True`` if ``member`` possesses the Classified role.

    The check is performed directly against :data:`CLASSIFIED_ROLE_ID` so that
    callers can reliably detect Classified operatives without relying on
    :func:`detect_clearance`'s return value.  This guards against situations
    where ``detect_clearance`` might fail (for example if role objects use
    unexpected types for their ``id`` attribute).
    """

    roles = getattr(member, "roles", [])
    role_ids = {getattr(r, "id", 0) for r in roles}
    if not role_ids:
        return False

    target_guild_id = guild_id if guild_id is not None else _guild_id_from_member(member)
    configured = {rid for rid in get_roles_for_level(6, target_guild_id) if rid}
    if configured and role_ids & configured:
        return True

    return CLASSIFIED_ROLE_ID in role_ids if CLASSIFIED_ROLE_ID else False


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


def detect_clearance(member, guild_id: int | None = None) -> int:
    """Return numeric clearance level for ``member`` based on roles."""
    target_guild_id = guild_id if guild_id is not None else _guild_id_from_member(member)

    if has_classified_clearance(member, target_guild_id):
        return 6

    roles = getattr(member, "roles", [])
    role_ids = {getattr(r, "id", 0) for r in roles}
    if target_guild_id is None and role_ids:
        logger.warning(
            "detect_clearance called without guild_id; role-mapped clearance may fall back."
        )

    for level in (5, 4, 3, 2, 1):
        configured = {rid for rid in get_roles_for_level(level, target_guild_id) if rid}
        if configured and role_ids & configured:
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
    if role_ids:
        configured_map = {
            level: [rid for rid in get_roles_for_level(level, target_guild_id) if rid]
            for level in (1, 2, 3, 4, 5, 6)
        }
        logger.warning(
            "Clearance fallback to L1 user=%s guild=%s roles=%s configured=%s",
            getattr(member, "id", None),
            target_guild_id,
            sorted(role_ids),
            configured_map,
        )
    return 1


def get_allowed_categories(level: int, categories: list[str]) -> list[str]:
    """Return ``categories`` without applying level-based filtering.

    Archive categories are visible to all operators regardless of their
    clearance level.  Access to individual files remains governed by file-level
    clearances.  ``level`` is accepted for backward compatibility but ignored.
    """

    return list(categories)


def generate_session_id() -> str:
    return "SES-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
