import os
import json
from typing import Any, Dict, Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def get_drive_service():
    """Return an authenticated Google Drive service using service-account creds.

    Credentials are expected in the ``GDRIVE_CREDS`` environment variable as a
    JSON string.  The service is configured with ``drive.file`` scope which is
    sufficient for reading and writing files that the service account owns or
    has been granted access to.
    """
    creds_json = os.getenv("GDRIVE_CREDS")
    if not creds_json:
        raise RuntimeError("GDRIVE_CREDS is not set")
    info = json.loads(creds_json)
    credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=credentials)

def upload_json(filename: str, content: Any, *, folder_id: Optional[str] = None, service=None) -> str:
    """Upload ``content`` to Google Drive as ``filename``.

    Parameters
    ----------
    filename:
        Name of the file to create in Drive.
    content:
        Data to serialise.  If ``dict`` or ``list`` it will be JSON encoded,
        otherwise it is assumed to be a JSON string or bytes.
    folder_id:
        Optional Drive folder ID.  If omitted the value from ``GDRIVE_FOLDER_ID``
        is used when available.
    service:
        Optional Drive service.  Primarily useful for testing; if ``None`` a
        service is constructed via :func:`get_drive_service`.
    """
    if service is None:
        service = get_drive_service()
    if isinstance(content, (dict, list)):
        data = json.dumps(content).encode("utf-8")
    elif isinstance(content, str):
        data = content.encode("utf-8")
    else:
        data = content
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/json")
    metadata: Dict[str, Any] = {"name": filename}
    parent = folder_id or os.getenv("GDRIVE_FOLDER_ID")
    if parent:
        metadata["parents"] = [parent]
    file = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return file["id"]

def download_json(file_id: str, *, service=None) -> Dict[str, Any]:
    """Download a JSON file from Drive and return its parsed content."""
    if service is None:
        service = get_drive_service()
    data = service.files().get(fileId=file_id, alt="media").execute()
    if isinstance(data, bytes):
        text = data.decode("utf-8")
    else:
        text = data
    return json.loads(text)
