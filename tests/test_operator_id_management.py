import importlib


def test_update_and_delete_operator(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    # Reload modules to apply new environment variables
    constants = importlib.reload(importlib.import_module("constants"))
    op_login = importlib.reload(importlib.import_module("operator_login"))

    op = op_login.get_or_create_operator(42)
    original = op.id_code
    op_login.update_id_code(42, "GU7-OPR-0001-AA")
    assert op_login.get_or_create_operator(42).id_code == "GU7-OPR-0001-AA"
    assert op_login.list_operators()
    op_login.delete_operator(42)
    assert all(r.user_id != 42 for r in op_login.list_operators())
    # Ensure original ID can be recreated
    op2 = op_login.get_or_create_operator(42)
    assert op2.id_code != "GU7-OPR-0001-AA"
