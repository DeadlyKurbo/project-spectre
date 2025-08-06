import json
import importlib

import utils


def test_grant_file_clearance_creates_file(tmp_path, monkeypatch):
    """Granting clearance on a fresh system should create the data file."""
    monkeypatch.delenv("SPECTRE_DATA_DIR", raising=False)
    importlib.reload(utils)
    missing = tmp_path / "clearance.json"
    # Point the module at our temporary, initially missing file
    monkeypatch.setattr(utils, "CLEARANCE_FILE", str(missing))

    # Should not raise even though the file does not yet exist
    utils.grant_file_clearance("alpha", "item", 1)

    assert missing.exists()
    data = json.loads(missing.read_text())
    assert data == {"alpha": {"item": [1]}}


def test_load_clearance_invalid_returns_empty(tmp_path, monkeypatch):
    """Invalid JSON should be treated as an empty configuration."""
    monkeypatch.delenv("SPECTRE_DATA_DIR", raising=False)
    importlib.reload(utils)
    broken = tmp_path / "clearance.json"
    broken.write_text("{not: valid}")
    monkeypatch.setattr(utils, "CLEARANCE_FILE", str(broken))

    assert utils.load_clearance() == {}


def test_clearance_respects_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECTRE_DATA_DIR", str(tmp_path))
    mod = importlib.reload(utils)
    expected = tmp_path / "clearance.json"
    mod.grant_file_clearance("alpha", "item", 1)
    assert expected.exists()
    assert json.loads(expected.read_text()) == {"alpha": {"item": [1]}}
    # Clean up for other tests
    monkeypatch.delenv("SPECTRE_DATA_DIR", raising=False)
    importlib.reload(utils)
