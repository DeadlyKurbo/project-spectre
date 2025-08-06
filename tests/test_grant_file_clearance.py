import json
import utils


def test_grant_file_clearance_does_not_add_extra_roles(tmp_path, monkeypatch):
    # Use a temporary clearance file
    tmp_clearance = tmp_path / 'clearance.json'
    tmp_clearance.write_text('{}')
    monkeypatch.setattr(utils, 'CLEARANCE_FILE', str(tmp_clearance))

    # Grant a role
    utils.grant_file_clearance('cat', 'item', 99)
    data = json.loads(tmp_clearance.read_text())
    assert data == {'cat': {'item': [99, utils.CLASSIFIED_ROLE_ID]}}

    # Grant another role and ensure previous remains without level 2
    utils.grant_file_clearance('cat', 'item', 100)
    data = json.loads(tmp_clearance.read_text())
    assert set(data['cat']['item']) == {99, 100, utils.CLASSIFIED_ROLE_ID}
    assert 1365094153901441075 not in data['cat']['item']
