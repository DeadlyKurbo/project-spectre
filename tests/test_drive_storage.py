from unittest.mock import MagicMock, patch

import json
import base64
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
    encoded = base64.b64encode(json.dumps(creds).encode("utf-8")).decode("utf-8")
    monkeypatch.setenv("GDRIVE_CREDS_BASE64", encoded)


@patch("drive_storage.build")
def test_get_drive_service_uses_env(build_mock, monkeypatch):
    _dummy_creds(monkeypatch)
    svc = object()
    build_mock.return_value = svc
    with patch("google.oauth2.service_account.Credentials.from_service_account_info") as cred_mock:
        cred_mock.return_value = object()
        assert get_drive_service() is svc
        build_mock.assert_called_once()
        cred_mock.assert_called_once()


@patch("drive_storage.build")
def test_get_drive_service_uses_file(build_mock, tmp_path, monkeypatch):
    creds = {
        "type": "service_account",
        "project_id": "dummy",
        "private_key_id": "1",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----\n",
        "client_email": "dummy@dummy.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    creds_path = tmp_path / "creds.json"
    creds_path.write_text(json.dumps(creds))
    monkeypatch.delenv("GDRIVE_CREDS_BASE64", raising=False)
    monkeypatch.setenv("GDRIVE_CREDS_FILE", str(creds_path))
    svc = object()
    build_mock.return_value = svc
    with patch("google.oauth2.service_account.Credentials.from_service_account_file") as cred_mock:
        cred_mock.return_value = object()
        assert get_drive_service() is svc
        build_mock.assert_called_once()
        cred_mock.assert_called_once()


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


def test_scopes_allow_full_drive_access():
    from drive_storage import SCOPES
    assert "https://www.googleapis.com/auth/drive" in SCOPES
