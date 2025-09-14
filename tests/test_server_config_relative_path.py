import importlib

def test_load_server_configs_resolves_module_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    import constants
    import server_config
    importlib.reload(constants)
    importlib.reload(server_config)
    configs = server_config.load_server_configs()
    assert 1416573746717659188 in configs
    assert configs[1416573746717659188].get("ROOT_PREFIX") == "records"
