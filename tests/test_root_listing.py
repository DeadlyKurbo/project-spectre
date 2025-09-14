import importlib

import utils

def test_list_dir_root_prefix_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("S3_ROOT_PREFIX", "")
    import storage_spaces
    importlib.reload(storage_spaces)
    monkeypatch.setattr(utils, "DOSSIERS_DIR", str(tmp_path))
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    dirs, files = storage_spaces.list_dir("")
    assert set(dirs) == {"alpha/", "beta/"}
    assert files == []
