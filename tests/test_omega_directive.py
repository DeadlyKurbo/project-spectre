import pytest

from omega_directive import OmegaDirectiveTest


def test_all_codes_pass():
    directive = OmegaDirectiveTest()
    directive.register_code("OMEGA_AUTH", "omega-44729")
    directive.register_code("OMEGA_LOCKDOWN", "lock-ALPHA")
    diagnostics = directive.test_codes(
        {"OMEGA_AUTH": "omega-44729", "OMEGA_LOCKDOWN": "lock-ALPHA"}
    )
    assert diagnostics == ["[PASS] All emergency codes validated successfully."]


def test_code_errors_and_missing():
    directive = OmegaDirectiveTest()
    directive.register_code("OMEGA_AUTH", "omega-44729")
    directive.register_code("OMEGA_LOCKDOWN", "lock-ALPHA")
    diagnostics = directive.test_codes({"OMEGA_AUTH": "wrong", "UNKNOWN": "1"})
    assert (
        "[ERROR] Code mismatch for 'OMEGA_AUTH': expected 'omega-44729', got 'wrong'"
        in diagnostics
    )
    assert "[ERROR] Unknown code name: UNKNOWN" in diagnostics
    assert "[WARN] Missing code: OMEGA_LOCKDOWN" in diagnostics


def test_duplicate_registration_raises():
    directive = OmegaDirectiveTest()
    directive.register_code("OMEGA_AUTH", "omega-44729")
    with pytest.raises(ValueError):
        directive.register_code("OMEGA_AUTH", "another")
    with pytest.raises(ValueError):
        directive.register_code("OMEGA_LOCKDOWN", "omega-44729")
