import os
import json
from typing import Any, Dict, Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# ``drive.file`` only grants access to files created by the service
# account.  In production the bot must read existing dossiers uploaded
# manually, so we request full Drive access to ensure the listing APIs
# can enumerate folders and files shared with the account.
SCOPES = ["https://www.googleapis.com/auth/drive"]

def get_drive_service():
    """Return an authenticated Google Drive service using service-account credentials.

    Historically credentials were supplied via the ``GDRIVE_CREDS`` environment
    variable containing the JSON payload.  The updated integration exposes a
    file path through ``GDRIVE_CREDS_FILE`` or the conventional
    ``GOOGLE_APPLICATION_CREDENTIALS``.  This helper accepts both formats to
    maintain backwards compatibility.
    """
    creds_json = os.getenv("GDRIVE_CREDS")
    creds_file = os.getenv("GDRIVE_CREDS_FILE") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if creds_json:
        info = json.loads(creds_json)
        credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
    elif creds_file:
        credentials = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    else:
        raise RuntimeError("GDRIVE_CREDS or GDRIVE_CREDS_FILE must be set")

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
