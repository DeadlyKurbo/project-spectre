import json
from pathlib import Path

import pytest

import utils


@pytest.fixture
def file_creation_utils(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    return utils


def test_create_dossier_file_creates_json(file_creation_utils):
    data = {"codename": "Agent A"}
    content = json.dumps(data)
    path = Path(file_creation_utils.create_dossier_file("intel", "agent_a", content))
    assert path.exists()
    assert json.loads(path.read_text()) == data


def test_create_dossier_file_converts_plain_text(file_creation_utils):
    text = "Agent B dossier"
    path = Path(file_creation_utils.create_dossier_file("intel", "agent_b", text))
    assert path.exists()
    assert json.loads(path.read_text()) == {"content": text}
