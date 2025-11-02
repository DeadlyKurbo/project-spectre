from utils import get_category_label


def test_get_category_label_uses_server_config(monkeypatch):
    def fake_get_server_config(guild_id):
        assert guild_id == 4242
        return {"CATEGORY_ORDER": [("xfiles", "X Files")]}

    monkeypatch.setattr("utils.server_config.get_server_config", fake_get_server_config)
    assert get_category_label("xfiles", guild_id=4242) == "X Files"
