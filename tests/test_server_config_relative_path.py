import importlib
import shutil
from pathlib import Path


def test_load_server_configs_resolves_module_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    import constants
    import server_config
    importlib.reload(constants)
    importlib.reload(server_config)
    cfg_dir = Path(server_config.__file__).resolve().parent
    example = cfg_dir / "server_configs.example.json"
    target = cfg_dir / "server_configs.json"
    shutil.copy(example, target)
    try:
        configs = server_config.load_server_configs()
    finally:
        target.unlink()
    assert 1416573746717659188 in configs
    assert configs[1416573746717659188].get("ROOT_PREFIX") == "records"
