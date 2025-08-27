import random
import string
import time
import hashlib
from dataclasses import dataclass
from typing import Dict

from constants import (
    LEVEL1_ROLE_ID,
    LEVEL2_ROLE_ID,
    LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID,
    LEVEL5_ROLE_ID,
    CLASSIFIED_ROLE_ID,
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


def _generate_id() -> str:
    """Return a pseudo-random digital operator ID."""
    block2 = f"{random.randint(0, 9999):04d}"
    block3 = "".join(random.choices(string.ascii_uppercase + string.digits, k=2))
    return f"GU7-{block2}-{block3}"


def get_or_create_operator(user_id: int) -> OperatorRecord:
    """Return existing operator record or create a new one."""
    op = _operators.get(user_id)
    if op is None:
        op = OperatorRecord(user_id=user_id, id_code=_generate_id())
        _operators[user_id] = op
    return op


def set_password(user_id: int, password: str) -> None:
    op = get_or_create_operator(user_id)
    op.password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    op.failed_attempts = 0
    op.locked_until = 0.0


def verify_password(user_id: int, password: str) -> tuple[bool, bool]:
    """Return (success, locked) after verifying ``password``."""
    op = get_or_create_operator(user_id)
    now = time.time()
    if op.locked_until and now < op.locked_until:
        return False, True
    if op.password_hash and hashlib.sha256(password.encode("utf-8")).hexdigest() == op.password_hash:
        op.failed_attempts = 0
        return True, False
    op.failed_attempts += 1
    if op.failed_attempts >= 3:
        op.locked_until = now + 300  # 5 minutes lockout
    return False, False


def set_clearance(user_id: int, level: int) -> None:
    get_or_create_operator(user_id).clearance = int(level)


def detect_clearance(member) -> int:
    """Return numeric clearance level for ``member`` based on roles."""
    roles = getattr(member, "roles", [])
    mapping = [
        (CLASSIFIED_ROLE_ID, 6),
        (LEVEL5_ROLE_ID, 5),
        (LEVEL4_ROLE_ID, 4),
        (LEVEL3_ROLE_ID, 3),
        (LEVEL2_ROLE_ID, 2),
        (LEVEL1_ROLE_ID, 1),
    ]
    for role_id, level in mapping:
        if any(r.id == role_id for r in roles):
            return level
    return 1


def get_allowed_categories(level: int, categories: list[str]) -> list[str]:
    """Return subset of ``categories`` allowed for given ``level``."""
    level = int(level)
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
