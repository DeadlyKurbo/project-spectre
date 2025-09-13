import importlib
from pathlib import Path

import boto3
from botocore.exceptions import EndpointConnectionError

import storage_spaces
import utils


def test_local_fallback_when_s3_unreachable(monkeypatch, tmp_path):
    # Pretend credentials are present so the module attempts to use S3
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "y")
    monkeypatch.setenv("S3_BUCKET", "z")

    # Block network access by making the client raise EndpointConnectionError
    class DummyClient:
        def list_objects_v2(self, **kwargs):
            raise EndpointConnectionError(endpoint_url="http://example.com")

    monkeypatch.setattr(boto3, "client", lambda *a, **k: DummyClient())
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)

    importlib.reload(storage_spaces)

    # Operations should now use the local filesystem fallback
    storage_spaces.ensure_dir("alpha")
    storage_spaces.save_text("alpha/file.txt", "data")
    assert storage_spaces.read_text("alpha/file.txt") == "data"
    assert storage_spaces._USE_SPACES is False

    # Cleanup: remove fake credentials and reload module for other tests
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    importlib.reload(storage_spaces)
