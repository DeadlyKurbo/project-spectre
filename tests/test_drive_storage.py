import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("google.oauth2.service_account")
pytest.importorskip("googleapiclient.discovery")

from drive_storage import get_drive_service, upload_json, download_json


def _dummy_creds(monkeypatch):
    creds = {
        "type": "service_account",
        "project_id": "dummy",
        "private_key_id": "1",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----\n",
        "client_email": "dummy@dummy.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    monkeypatch.setenv("GDRIVE_CREDS", json.dumps(creds))


@patch("drive_storage.build")
def test_get_drive_service_uses_env(build_mock, monkeypatch):
    _dummy_creds(monkeypatch)
    svc = object()
    build_mock.return_value = svc
    assert get_drive_service() is svc
    build_mock.assert_called_once()


def test_upload_json_calls_api(monkeypatch):
    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = {"id": "abc"}
    result = upload_json("file.json", {"a": 1}, folder_id="folder", service=service)
    assert result == "abc"
    service.files.return_value.create.assert_called_once()
    body = service.files.return_value.create.call_args.kwargs["body"]
    assert body["name"] == "file.json"
    assert body["parents"] == ["folder"]


def test_download_json_parses(monkeypatch):
    service = MagicMock()
    service.files.return_value.get.return_value.execute.return_value = b'{"x":2}'
    result = download_json("id1", service=service)
    assert result == {"x": 2}
    service.files.return_value.get.assert_called_once_with(fileId="id1", alt="media")
