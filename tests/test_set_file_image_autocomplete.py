import main


def test_autocomplete_items(monkeypatch):
    monkeypatch.setattr(main, "list_items_recursive", lambda c, max_items=25: ["alpha", "beta", "alpine"])
    assert main._autocomplete_items("intel", "al") == ["alpha", "alpine"]
    assert main._autocomplete_items("intel", "b") == ["beta"]


def test_autocomplete_items_missing_category(monkeypatch):
    def raiser(c, max_items=25):
        raise FileNotFoundError
    monkeypatch.setattr(main, "list_items_recursive", raiser)
    assert main._autocomplete_items("missing", "") == []
