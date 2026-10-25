import dossier
import utils


def test_create_dossier_file_preserves_spaces(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    key = dossier.create_dossier_file("intel", "foo bar", "hello", prefer_txt_default=True)
    assert key == "dossiers/intel/foo bar.txt"
    saved = tmp_path / "intel" / "foo bar.txt"
    assert saved.read_text() == "hello"
