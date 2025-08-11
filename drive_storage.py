# drive_storage.py
# Google Drive OAuth helper + persistent JSON storage + folder map refresh.
# Fixes "invalid_scope" by using the token's scopes when present.

import os
import io
import json
import base64
import datetime as dt
from typing import Dict, List, Optional, Tuple

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# ── ENV NAMES ──────────────────────────────────────────────────────────────
ENV_CLIENT_BASE64 = "GDRIVE_CREDS_BASE64"       # base64 of OAuth client JSON
ENV_CLIENT_JSON   = "GDRIVE_CREDS"              # raw JSON (fallback)
ENV_TOKEN_BASE64  = "GDRIVE_TOKEN_JSON_BASE64"  # base64 of token.json
ENV_TOKEN_JSON    = "GDRIVE_TOKEN_JSON"         # raw JSON (fallback)
ENV_ROOT_FOLDER   = "GDRIVE_FOLDER_ID"          # your bot's root folder ID

# Desired scopes only used when there is no token yet:
DESIRED_SCOPES: List[str] = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

# Filenames we persist inside the root folder:
SETTINGS_NAME   = "bot_settings.json"
CLEARANCES_NAME = "file_clearances.json"
FOLDERS_NAME    = "folder_map.json"


# ── INTERNAL HELPERS ───────────────────────────────────────────────────────
def _maybe_b64_to_json(s: Optional[str]) -> Optional[Dict]:
    if not s:
        return None
    s = s.strip().strip('"').strip("'")
    try:
        return json.loads(base64.b64decode(s).decode("utf-8"))
    except Exception:
        pass
    try:
        return json.loads(s)
    except Exception:
        return None


def _load_client_info() -> Dict:
    data = _maybe_b64_to_json(os.getenv(ENV_CLIENT_BASE64)) or _maybe_b64_to_json(os.getenv(ENV_CLIENT_JSON))
    if not data:
        raise RuntimeError("Missing Google OAuth client. Set GDRIVE_CREDS_BASE64 or GDRIVE_CREDS.")
    return data


def _load_token_info() -> Optional[Dict]:
    return _maybe_b64_to_json(os.getenv(ENV_TOKEN_BASE64)) or _maybe_b64_to_json(os.getenv(ENV_TOKEN_JSON))


# ── AUTH / SERVICE ─────────────────────────────────────────────────────────
def get_credentials() -> Credentials:
    client_info = _load_client_info()
    token_info = _load_token_info()

    if token_info:
        creds = Credentials.from_authorized_user_info(info=token_info)  # keep EXACT token scopes
    else:
        creds = Credentials(
            token=None,
            refresh_token=None,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=(client_info.get("installed", {}) or client_info.get("web", {})).get("client_id"),
            client_secret=(client_info.get("installed", {}) or client_info.get("web", {})).get("client_secret"),
            scopes=DESIRED_SCOPES,
        )

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def get_drive_service():
    try:
        return build("drive", "v3", credentials=get_credentials(), cache_discovery=False)
    except Exception as e:
        raise RuntimeError(f"Failed to build Drive service: {e}") from e


# ── GENERIC JSON FILE OPS (BY NAME INSIDE ROOT FOLDER) ─────────────────────
def _root_id() -> str:
    rid = os.getenv(ENV_ROOT_FOLDER)
    if not rid:
        raise RuntimeError("Missing GDRIVE_FOLDER_ID env.")
    return rid


def _find_by_name(service, parent_id: str, name: str) -> Optional[str]:
    q = f"'{parent_id}' in parents and name = '{name}' and trashed=false"
    page_token = None
    while True:
        resp = service.files().list(
            q=q, fields="nextPageToken, files(id, name)", pageToken=page_token
        ).execute()
        files = resp.get("files", [])
        if files:
            return files[0]["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            return None


def _create_json(service, parent_id: str, name: str, data: Dict) -> str:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(body), mimetype="application/json", resumable=False)
    meta = {"name": name, "parents": [parent_id]}
    created = service.files().create(body=meta, media_body=media, fields="id").execute()
    return created["id"]


def _update_json(service, file_id: str, data: Dict) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(body), mimetype="application/json", resumable=False)
    service.files().update(fileId=file_id, media_body=media).execute()


def _read_json(service, file_id: str) -> Dict:
    req = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return json.loads(buf.read().decode("utf-8"))


def ensure_json(name: str, default_data: Dict) -> Tuple[str, Dict]:
    """Ensure <name> exists in root and return (file_id, data)."""
    service = get_drive_service()
    rid = _root_id()
    fid = _find_by_name(service, rid, name)
    if fid is None:
        fid = _create_json(service, rid, name, default_data)
        return fid, default_data
    return fid, _read_json(service, fid)


def write_json(name: str, data: Dict) -> str:
    service = get_drive_service()
    rid = _root_id()
    fid = _find_by_name(service, rid, name)
    if fid is None:
        return _create_json(service, rid, name, data)
    _update_json(service, fid, data)
    return fid


# ── PUBLIC SIMPLE APIS YOUR BOT USES ───────────────────────────────────────
def debug_dump() -> str:
    client_present = _load_client_info() is not None
    token_info = _load_token_info()
    token_present = token_info is not None
    scopes = token_info.get("scopes", []) if token_info else []
    if isinstance(scopes, str):
        scopes = [scopes]

    lines = []
    lines.append("drive_storage.SCOPES (desired if no token):")
    lines.append(json.dumps(DESIRED_SCOPES, indent=2))
    lines.append("")
    lines.append(f"GDRIVE_CREDS present: {client_present}")
    lines.append(f"token.json present: {token_present}")
    if token_present:
        lines.append("scopes in token.json:")
        lines.append(json.dumps(scopes, indent=2))
        lines.append(f"client_id in token.json: {token_info.get('client_id', '—')}")
    lines.append(f"GDRIVE_FOLDER_ID: {os.getenv(ENV_ROOT_FOLDER, '—')}")
    return "\n".join(lines)


# SETTINGS (log channel, timestamps, …)
def get_settings() -> Dict:
    _, data = ensure_json(SETTINGS_NAME, {"log_channel_id": None, "last_refresh": None})
    return data


def save_settings(data: Dict) -> str:
    return write_json(SETTINGS_NAME, data)


# CLEARANCES (per file id)
def get_clearances() -> Dict:
    _, data = ensure_json(CLEARANCES_NAME, {"items": {}})
    return data


def save_clearances(data: Dict) -> str:
    return write_json(CLEARANCES_NAME, data)


# FOLDER MAP (id -> {name, mimeType, path})
def get_folder_map() -> Dict:
    _, data = ensure_json(FOLDERS_NAME, {"generated_at": None, "root": None, "items": {}})
    return data


def refresh_folder_map() -> Dict:
    """
    Recursively scans the root folder and writes folder_map.json.
    Returns the map dict.
    """
    service = get_drive_service()
    root_id = _root_id()

    items: Dict[str, Dict] = {}

    def list_children(pid: str) -> List[Dict]:
        q = f"'{pid}' in parents and trashed=false"
        page_token = None
        out = []
        while True:
            resp = service.files().list(
                q=q,
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token,
                pageSize=1000,
            ).execute()
            out.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return out

    def walk(pid: str, prefix: str):
        children = list_children(pid)
        for f in children:
            fid = f["id"]
            name = f["name"]
            mime = f.get("mimeType", "")
            path = f"{prefix}/{name}" if prefix else name
            items[fid] = {"name": name, "mimeType": mime, "path": path, "parent": pid}
            if mime == "application/vnd.google-apps.folder":
                walk(fid, path)

    walk(root_id, "")

    data = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "root": root_id,
        "items": items,
    }
    write_json(FOLDERS_NAME, data)
    return data
