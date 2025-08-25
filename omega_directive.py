"""Omega Directive – Test Harness.

This module simulates a minimal Omega Directive interface that can be used to
verify emergency codes. It performs no real actions; it only validates provided
codes against registered ones and reports potential issues.
"""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class EmergencyCode:
    """Represents an emergency code in the Omega Directive system."""

    name: str
    value: str
    description: str = ""


@dataclass
class OmegaDirectiveTest:
    """Test harness for validating Omega Directive emergency codes."""

    codes: Dict[str, EmergencyCode] = field(default_factory=dict)

    def register_code(self, name: str, value: str, description: str = "") -> None:
        """Register a new emergency code.

        Raises ``ValueError`` if a duplicate name or value is detected.
        """
        if name in self.codes:
            raise ValueError(f"Duplicate code name detected: {name}")
        if any(c.value == value for c in self.codes.values()):
            raise ValueError(f"Duplicate code value detected: {value}")
        self.codes[name] = EmergencyCode(name, value, description)

    def test_codes(self, provided_codes: Dict[str, str]) -> List[str]:
        """Validate a set of provided codes.

        Returns a list of diagnostics (errors or warnings). If all codes match,
        a single ``[PASS]`` message is returned.
        """
        diagnostics: List[str] = []
        for name, value in provided_codes.items():
            if name not in self.codes:
                diagnostics.append(f"[ERROR] Unknown code name: {name}")
                continue
            expected_value = self.codes[name].value
            if value != expected_value:
                diagnostics.append(
                    f"[ERROR] Code mismatch for '{name}': expected '{expected_value}', got '{value}'"
                )
        for name in self.codes:
            if name not in provided_codes:
                diagnostics.append(f"[WARN] Missing code: {name}")
        if not diagnostics:
            diagnostics.append("[PASS] All emergency codes validated successfully.")
        return diagnostics


if __name__ == "__main__":
    # Example setup and invocation
    directive = OmegaDirectiveTest()
    directive.register_code("OMEGA_AUTH", "omega-44729", "Primary activation code")
    directive.register_code("OMEGA_LOCKDOWN", "lock-ALPHA", "Lockdown override")

    sample_input = {
        "OMEGA_AUTH": "omega-44729",
        "OMEGA_LOCKDOWN": "lock-ALPHA",
    }
    results = directive.test_codes(sample_input)
    print("Omega Directive Test Results:")
    for r in results:
        print("  ", r)
