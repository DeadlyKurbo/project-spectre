import importlib

import pytest


@pytest.fixture
def persistent_store_module():
    import persistent_store

    return importlib.reload(persistent_store)


def test_defaults_to_spaces_backend(monkeypatch, persistent_store_module):
    monkeypatch.delenv("PERSISTENCE_BACKEND", raising=False)
    backend = persistent_store_module.get_backend()
    assert backend.__class__.__name__ == "SpacesPersistenceBackend"


def test_railway_backend_requires_database_url(monkeypatch, persistent_store_module):
    monkeypatch.setenv("PERSISTENCE_BACKEND", "railway")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        persistent_store_module.get_backend()


def test_railway_sqlite_roundtrip(monkeypatch, tmp_path, persistent_store_module):
    db_path = tmp_path / "spectre-test.db"
    monkeypatch.setenv("PERSISTENCE_BACKEND", "railway")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    persistent_store_module.save_json("config/config.json", {"build_version": "v3.0.0"})
    payload = persistent_store_module.read_json("config/config.json")

    assert payload["build_version"] == "v3.0.0"


def test_unknown_backend_fails_fast(monkeypatch, persistent_store_module):
    monkeypatch.setenv("PERSISTENCE_BACKEND", "mystery")
    with pytest.raises(RuntimeError):
        persistent_store_module.get_backend()
