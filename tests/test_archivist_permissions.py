import types

def test_removal_author_id_for_lead(monkeypatch):
    import archivist
    monkeypatch.setattr(archivist, "_is_lead_archivist", lambda u: True)
    user = types.SimpleNamespace(id=42)
    assert archivist._removal_author_id(user) is None

def test_removal_author_id_for_regular(monkeypatch):
    import archivist
    monkeypatch.setattr(archivist, "_is_lead_archivist", lambda u: False)
    user = types.SimpleNamespace(id=99)
    assert archivist._removal_author_id(user) == 99
