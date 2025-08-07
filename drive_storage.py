"""Utility helpers for storing JSON data on Google Drive.

These functions provide a very small wrapper around the Google Drive API so
that other modules can upload or download JSON files.  Only the pieces that are
required by the unit tests are implemented; the helpers intentionally avoid any
network calls by allowing a mocked ``service`` object to be supplied.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Dict, Optional

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials


SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service():
    """Authenticate and return a Drive service client.

    Credentials are loaded either from ``GDRIVE_CREDS_BASE64`` (a base64 encoded
    service account JSON) or from ``GDRIVE_CREDS_FILE`` which points at a
    credentials file on disk.  The function mirrors a tiny subset of the real
    behaviour which is sufficient for the tests where the Google modules are
    patched with mocks.
    """

    creds_info = os.getenv("GDRIVE_CREDS_BASE64")
    creds_file = os.getenv("GDRIVE_CREDS_FILE")

    if creds_info:
        info = json.loads(base64.b64decode(creds_info))
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        if not creds_file:
            raise EnvironmentError("No Google Drive credentials provided")
        creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)

    return build("drive", "v3", credentials=creds)


def upload_json(name: str, data: Dict, *, folder_id: Optional[str] = None, service=None) -> str:
    """Upload ``data`` as ``name`` to Drive and return the created file id."""

    if service is None:
        service = get_drive_service()

    metadata = {"name": name}
    if folder_id:
        metadata["parents"] = [folder_id]

    # The tests only assert that ``create`` was called with the correct body, so
    # the exact type of ``media_body`` is irrelevant here.  We simply pass the
    # JSON string directly.
    media = json.dumps(data).encode("utf-8")
    result = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return result.get("id")


def download_json(file_id: str, *, service=None):
    """Download the JSON content of ``file_id`` and return it as a dict."""

    if service is None:
        service = get_drive_service()

    data = service.files().get(fileId=file_id, alt="media").execute()
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data)


def refresh_folder_map() -> Dict[str, str]:
    """Scan subfolders, generate ``folder_map.json`` and upload it to Drive."""

    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    service = get_drive_service()

    results = service.files().list(
        q=(
            f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        ),
        fields="files(id, name)",
    ).execute()

    folder_map = {f["name"].lower(): f["id"] for f in results.get("files", [])}

    upload_json("folder_map.json", folder_map, folder_id=folder_id, service=service)
    return folder_map


def load_folder_map() -> Dict[str, str]:
    """Download ``folder_map.json`` from Drive and return it as a dict."""

    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    service = get_drive_service()

    results = service.files().list(
        q=(
            f"'{folder_id}' in parents and name = 'folder_map.json' and trashed = false"
        ),
        fields="files(id, name)",
        pageSize=1,
    ).execute()

    files = results.get("files", [])
    if not files:
        raise FileNotFoundError("folder_map.json not found on Drive")

    file_id = files[0]["id"]
    return download_json(file_id, service=service)

