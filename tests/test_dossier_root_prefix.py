import importlib


def _reload_dossier():
    module = importlib.import_module("dossier")
    return importlib.reload(module)


class _FakeConfig:
    def __init__(self, value):
        self._value = value

    def get(self, key, default=None):
        assert key == "ROOT_PREFIX"
        return self._value


def test_root_prefix_uses_config(monkeypatch):
    dossier = _reload_dossier()
    monkeypatch.setattr(dossier, "get_server_config", lambda gid: _FakeConfig(" /custom/ "))
    assert dossier._root_prefix(123) == "custom"


def test_root_prefix_fallback_scoped(monkeypatch):
    dossier = _reload_dossier()
    monkeypatch.setattr(dossier, "get_server_config", lambda gid: _FakeConfig(""))
    assert dossier._root_prefix(321) == f"{dossier.ROOT_PREFIX}/321"


def test_root_prefix_default():
    dossier = _reload_dossier()
    assert dossier._root_prefix(None) == dossier.ROOT_PREFIX


def test_archive_root_prefixes_include_legacy_root_for_default_scoped_guild(monkeypatch):
    dossier = _reload_dossier()
    monkeypatch.setattr(dossier, "ROOT_PREFIX", "dossiers")
    monkeypatch.setattr(dossier, "get_server_config", lambda gid: _FakeConfig(""))

    roots = dossier._archive_root_prefixes(guild_id=77)

    assert roots == ["dossiers/77", "dossiers"]


def test_archive_root_prefixes_skip_legacy_when_root_explicit(monkeypatch):
    dossier = _reload_dossier()
    monkeypatch.setattr(dossier, "ROOT_PREFIX", "dossiers")
    monkeypatch.setattr(dossier, "get_server_config", lambda gid: _FakeConfig("custom-root"))

    roots = dossier._archive_root_prefixes(guild_id=77)

    assert roots == ["custom-root"]
