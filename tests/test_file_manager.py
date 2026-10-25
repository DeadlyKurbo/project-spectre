import json
from pathlib import Path

import pytest

from file_manager import FileManager


@pytest.fixture
def fm(tmp_path):
    return FileManager(tmp_path)


def test_add_creates_file(fm):
    path = Path(fm.add("intel", "agent_c", {"codename": "Agent C"}))
    assert path.exists()
    assert json.loads(path.read_text()) == {"codename": "Agent C"}


def test_update_overwrites_content(fm):
    fm.add("intel", "agent_d", {"codename": "Agent D"})
    fm.update("intel", "agent_d", {"codename": "Agent D", "status": "active"})
    path = fm.base_dir / "intel" / "agent_d.json"
    assert json.loads(path.read_text()) == {"codename": "Agent D", "status": "active"}


def test_remove_deletes_file(fm):
    fm.add("intel", "agent_e", "data")
    fm.remove("intel", "agent_e")
    assert not (fm.base_dir / "intel" / "agent_e.json").exists()
