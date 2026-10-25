import json

import utils


def test_grant_file_clearance_creates_file(tmp_path, monkeypatch):
    """Granting clearance on a fresh system should create the data file."""
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
    broken = tmp_path / "clearance.json"
    broken.write_text("{not: valid}")
    monkeypatch.setattr(utils, "CLEARANCE_FILE", str(broken))

    assert utils.load_clearance() == {}
