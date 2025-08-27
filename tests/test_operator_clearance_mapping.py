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
    expected = {
        1: {"missions", "personnel"},
        2: {"missions", "personnel", "intel"},
        3: {"missions", "personnel", "intel", "fleet"},
        4: {
            "missions",
            "personnel",
            "intel",
            "fleet",
            "tech_equipment",
            "active_efforts",
        },
        5: {
            "missions",
            "personnel",
            "intel",
            "fleet",
            "tech_equipment",
            "active_efforts",
            "high_command_directives",
            "protocols_contingencies",
        },
    }
    for level, cats in expected.items():
        assert set(get_allowed_categories(level, all_cats)) == cats
