import importlib


def test_link_registry_register_and_resolve(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    import utils  # pylint: disable=import-error

    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    import link_registry  # pylint: disable=import-error
    importlib.reload(link_registry)

    code = link_registry.get_instance_code()
    assert isinstance(code, str) and code

    link_registry.register_archive(123456789, root_prefix="records/main", name="Primary Archive")

    resolved = link_registry.resolve_code(code)
    assert resolved["code"] == code
    archives = resolved.get("archives")
    assert isinstance(archives, list)
    assert archives and archives[0]["root_prefix"] == "records/main"
    assert archives[0].get("name") == "Primary Archive"

    summary = link_registry.get_instance_summary()
    assert summary["code"] == code
    assert summary["archives"]

    link_registry.unregister_archive(123456789)
    resolved_after = link_registry.resolve_code(code)
    assert resolved_after.get("archives") == []
