import importlib
import storage_spaces


def test_temp_clearance(monkeypatch, tmp_path):
    monkeypatch.setenv("GUILD_ID", "1")
    acl = importlib.import_module("acl")
    monkeypatch.setattr(storage_spaces, "_local_root", lambda: str(tmp_path))
    monkeypatch.setattr(acl, "ROOT_PREFIX", "tmp")
    monkeypatch.setattr(acl, "TEMP_CLEARANCE_KEY", "tmp/acl/temp.json")

    now = 1000
    monkeypatch.setattr(acl.time, "time", lambda: now)
    acl.grant_temp_clearance("missions", "alpha", 42, ttl_seconds=10)
    assert acl.check_temp_clearance(42, "missions", "alpha")

    monkeypatch.setattr(acl.time, "time", lambda: now + 11)
    assert not acl.check_temp_clearance(42, "missions", "alpha")
    assert storage_spaces.read_json("tmp/acl/temp.json") == {}

    # One-time clearance: granted once, consumed on first access
    acl.grant_one_time_clearance("intel", "report", 99)
    assert acl.check_temp_clearance(99, "intel", "report")
    assert not acl.check_temp_clearance(99, "intel", "report")  # consumed
    assert not acl.check_temp_clearance(99, "intel", "other")  # wrong file

