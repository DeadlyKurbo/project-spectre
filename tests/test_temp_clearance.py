import importlib
import storage_spaces


def test_temp_clearance(monkeypatch, tmp_path):
    monkeypatch.setenv("GUILD_ID", "1")
    acl = importlib.import_module("acl")
    monkeypatch.setattr(storage_spaces, "_local_root", lambda: str(tmp_path))

    now = 1000
    with storage_spaces.using_root_prefix("tmp"):
        monkeypatch.setattr(acl.time, "time", lambda: now)
        acl.grant_temp_clearance("missions", "alpha", 42, ttl_seconds=10)
        assert acl.check_temp_clearance(42, "missions", "alpha")

        monkeypatch.setattr(acl.time, "time", lambda: now + 11)
        assert not acl.check_temp_clearance(42, "missions", "alpha")
        assert storage_spaces.read_json("acl/temp_clearance.json") == {}

