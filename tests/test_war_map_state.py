import pytest

from war_map import (
    PYRO_WAR_DEFAULT_FOCUS,
    load_pyro_war_state,
    sanitize_pyro_war_state,
    save_pyro_war_state,
)


def test_sanitize_pyro_war_state_normalises_values():
    payload = sanitize_pyro_war_state(
        {"pyro-iii": "Friendly ", "pyro-i": "bogus"},
        "  Advance on Pyro IV  ",
    )
    assert payload["battle_readiness"]["pyro-iii"] == "friendly"
    assert payload["battle_readiness"]["pyro-i"] == "inactive"
    assert payload["attack_focus"] == "Advance on Pyro IV"


def test_load_pyro_war_state_returns_defaults(monkeypatch):
    def fake_read_json(*_, **__):  # noqa: ANN001
        raise FileNotFoundError("missing")

    monkeypatch.setattr("war_map.read_json", fake_read_json)
    state = load_pyro_war_state()
    assert state["battle_readiness"]["pyro-iii"] == "friendly"
    assert state["attack_focus"] == PYRO_WAR_DEFAULT_FOCUS


def test_save_pyro_war_state_sanitises(monkeypatch):
    captured = {}

    def fake_write(path, data, *, etag=None):  # noqa: ANN001
        captured["path"] = path
        captured["data"] = data
        captured["etag"] = etag
        return True

    monkeypatch.setattr("war_map.write_json", fake_write)
    result = save_pyro_war_state({"pyro-ii": "Friendly", "unknown": "contested"}, "  Hold shell  ", etag="abc")
    assert result is True
    readiness = captured["data"]["battle_readiness"]
    assert readiness["pyro-ii"] == "friendly"
    assert readiness["pyro-i"] == "inactive"
    assert captured["data"]["attack_focus"] == "Hold shell"
    assert captured["etag"] == "abc"
