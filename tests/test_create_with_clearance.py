import json
import utils


def test_create_dossier_with_clearance(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    monkeypatch.setattr(utils, "CLEARANCE_FILE", tmp_path / "clearance.json")
    path = utils.create_dossier_with_clearance("intel", "ghost", "{\"a\":1}", 123)
    expected = tmp_path / "intel" / "ghost.json"
    assert path == str(expected)
    assert expected.exists()
    data = utils.load_clearance()
    assert data == {"intel": {"ghost": [123]}}
    assert json.loads(expected.read_text()) == {"a": 1}
