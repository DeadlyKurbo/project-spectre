import storage_spaces
import acl


def test_acl_root_prefix_isolation(tmp_path, monkeypatch):
    # Route each storage root to its own directory under ``tmp_path``
    def _root():
        return str(tmp_path / storage_spaces.get_root_prefix())

    monkeypatch.setattr(storage_spaces, "_local_root", _root)

    # Write clearance under the default root (dossiers)
    acl.grant_file_clearance("intel", "agent", 1)

    # Write clearance under a separate Section Zero root
    with storage_spaces.using_root_prefix("section_zero"):
        acl.grant_file_clearance("intel", "ghost", 2)

    # Verify files are isolated
    main_data = storage_spaces.read_json("acl/clearance.json")
    with storage_spaces.using_root_prefix("section_zero"):
        zero_data = storage_spaces.read_json("acl/clearance.json")

    assert "agent" in main_data.get("intel", {})
    assert "ghost" not in main_data.get("intel", {})
    assert "ghost" in zero_data.get("intel", {})
    assert "agent" not in zero_data.get("intel", {})
