from server_config import ServerConfig, SERVER_CONFIGS
from utils import get_category_label


def test_get_category_label_uses_server_config(monkeypatch):
    cfg = ServerConfig({"CATEGORY_ORDER": [("xfiles", "X Files")]})
    monkeypatch.setitem(SERVER_CONFIGS, 4242, cfg)
    assert get_category_label("xfiles", guild_id=4242) == "X Files"
