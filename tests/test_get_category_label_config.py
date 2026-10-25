from server_config import ServerConfig, SERVER_CONFIGS
from utils import get_category_label


def test_get_category_label_ignores_server_override(monkeypatch):
    cfg = ServerConfig({"CATEGORY_ORDER": [("personnel", "Agents")]})
    monkeypatch.setitem(SERVER_CONFIGS, 4242, cfg)
    assert get_category_label("personnel", guild_id=4242) == "Personnel"
