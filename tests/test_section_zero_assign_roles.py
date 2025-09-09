from constants import SECTION_ZERO_ASSIGN_ROLES, INQUISITOR_ROLE_ID

def test_inquisitor_role_present_in_assign_roles():
    assert INQUISITOR_ROLE_ID in SECTION_ZERO_ASSIGN_ROLES
