from operator_login import detect_clearance, get_allowed_categories
from constants import (
    LEVEL1_ROLE_ID,
    LEVEL2_ROLE_ID,
    LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID,
    LEVEL5_ROLE_ID,
    CLASSIFIED_ROLE_ID,
    CATEGORY_ORDER,
)


class DummyRole:
    def __init__(self, role_id):
        self.id = role_id


class DummyMember:
    def __init__(self, role_ids):
        self.roles = [DummyRole(rid) for rid in role_ids]


def test_detect_clearance_highest_role():
    member = DummyMember([LEVEL2_ROLE_ID, LEVEL4_ROLE_ID])
    assert detect_clearance(member) == 4
    member = DummyMember([CLASSIFIED_ROLE_ID])
    assert detect_clearance(member) == 6
    member = DummyMember([])
    assert detect_clearance(member) == 1


def test_get_allowed_categories_per_level():
    all_cats = [slug for slug, _ in CATEGORY_ORDER]
    extras = all_cats + ["omega", "secret"]
    for level in range(1, 7):
        assert get_allowed_categories(level, all_cats) == all_cats
        assert get_allowed_categories(level, extras) == extras
