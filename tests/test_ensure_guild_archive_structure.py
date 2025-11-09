import dossier


def test_ensure_guild_archive_structure_uses_default(monkeypatch):
    calls = []
    monkeypatch.setattr(dossier, "ensure_dir", lambda prefix: calls.append(prefix))
    monkeypatch.setattr(dossier, "_root_prefix", lambda guild_id: "alpha")

    result = dossier.ensure_guild_archive_structure(5)

    assert result == "alpha"
    assert calls == ["alpha", "alpha/_archived"]


def test_ensure_guild_archive_structure_with_override(monkeypatch):
    calls = []
    monkeypatch.setattr(dossier, "ensure_dir", lambda prefix: calls.append(prefix))

    result = dossier.ensure_guild_archive_structure(5, root_prefix="beta/path")

    assert result == "beta/path"
    assert calls == ["beta/path", "beta/path/_archived"]
