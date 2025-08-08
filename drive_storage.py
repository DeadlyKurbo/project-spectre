import os
import io
import json
import base64
from typing import Dict, List, Tuple, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ====== Scopes (must match the token.json scopes) ======
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

TOKEN_PATH = "token.json"
FOLDER_MAP_CACHE = "folder_map.json"
ROOT_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "").strip()

# Drive config singleton
DRIVE_CONFIG_NAME = "_spectre_config.json"  # stored in root folder


# ---------- Token / Service ----------
def _ensure_token_file():
    """Always write token.json from Railway var if present."""
    b64 = os.getenv("GDRIVE_CREDS_BASE64")
    if b64:
        try:
            raw = base64.b64decode(b64).decode("utf-8")
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(raw)
        except Exception as e:
            print(f"[drive_storage] Failed to write token.json from env: {e}")

def get_drive_service():
    _ensure_token_file()
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError("token.json missing. Provide GDRIVE_CREDS_BASE64.")
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    return build("drive", "v3", credentials=creds)


# ---------- Folder map ----------
def _is_folder(obj: dict) -> bool:
    return obj.get("mimeType") == "application/vnd.google-apps.folder"

def _list_children(service, parent_id: str, query_extra: Optional[str] = None) -> List[dict]:
    q_parts = [f"'{parent_id}' in parents", "trashed = false"]
    if query_extra:
        q_parts.append(query_extra)
    q = " and ".join(q_parts)

    items: List[dict] = []
    token = None
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                fields="nextPageToken, files(id,name,mimeType)",
                pageSize=1000,
                pageToken=token,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            )
            .execute()
        )
        items.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return items

def _collect_json_recursively(service, parent_id: str, prefix: str = "") -> Dict[str, dict]:
    results: Dict[str, dict] = {}
    children = _list_children(service, parent_id)
    for item in children:
        if _is_folder(item):
            sub_prefix = f"{prefix}{item['name']}/"
            results.update(_collect_json_recursively(service, item["id"], sub_prefix))
        else:
            name = item["name"]
            if not name.lower().endswith(".json"):
                continue
            stem = name[:-5]
            key = f"{prefix}{stem}" if prefix else stem
            results[key] = {"id": item["id"], "name": name, "path": f"{prefix}{name}"}
    return results

def refresh_folder_map(root_folder_id: Optional[str] = None) -> Dict[str, dict]:
    root_id = (root_folder_id or ROOT_FOLDER_ID).strip()
    if not root_id:
        raise ValueError("GDRIVE_FOLDER_ID env var missing.")
    service = get_drive_service()
    try:
        categories = _list_children(
            service, root_id, "mimeType='application/vnd.google-apps.folder'"
        )
        folder_map: Dict[str, dict] = {}
        for cat in categories:
            cat_name = cat["name"]
            cat_id = cat["id"]
            items = _collect_json_recursively(service, cat_id)
            folder_map[cat_name] = {"id": cat_id, "items": items}
        with open(FOLDER_MAP_CACHE, "w", encoding="utf-8") as fp:
            json.dump(folder_map, fp, indent=2, ensure_ascii=False)
        return folder_map
    except HttpError as e:
        raise RuntimeError(f"Drive API error while refreshing folder map: {e}")

def load_folder_map() -> Dict[str, dict]:
    if not os.path.exists(FOLDER_MAP_CACHE):
        raise FileNotFoundError("folder_map.json missing. Run refresh first.")
    with open(FOLDER_MAP_CACHE, "r", encoding="utf-8") as fp:
        return json.load(fp)


# ---------- Dossier content ----------
def fetch_dossier_json(file_id: str) -> Tuple[dict, str]:
    service = get_drive_service()
    try:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        text = fh.read().decode("utf-8", errors="replace")
        data = json.loads(text)
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        return data, pretty
    except HttpError as e:
        raise RuntimeError(f"Drive download error: {e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON content: {e}")


# ---------- Drive-backed config ----------
def _find_config_file_id(service) -> Optional[str]:
    if not ROOT_FOLDER_ID:
        return None
    resp = service.files().list(
        q=f"name='{DRIVE_CONFIG_NAME}' and '{ROOT_FOLDER_ID}' in parents and trashed=false",
        fields="files(id,name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        pageSize=1,
    ).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None

def get_drive_config() -> dict:
    """Load _spectre_config.json from Drive; returns {} if missing."""
    if not ROOT_FOLDER_ID:
        return {}
    service = get_drive_service()
    file_id = _find_config_file_id(service)
    if not file_id:
        return {}
    try:
        req = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        buf.seek(0)
        return json.loads(buf.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}

def save_drive_config(data: dict) -> str:
    """Create or overwrite _spectre_config.json in the root folder."""
    service = get_drive_service()
    media = MediaIoBaseUpload(
        io.BytesIO(json.dumps(data, indent=2).encode("utf-8")),
        mimetype="application/json",
        resumable=False,
    )
    file_id = _find_config_file_id(service)
    if file_id:
        service.files().update(
            fileId=file_id,
            media_body=media,
            supportsAllDrives=True,
        ).execute()
        return file_id
    meta = {"name": DRIVE_CONFIG_NAME, "parents": [ROOT_FOLDER_ID]}
    created = service.files().create(
        body=meta, media_body=media, fields="id", supportsAllDrives=True
    ).execute()
    return created["id"]


# ---------- Per-file clearance via appProperties ----------
ACL_KEY = "spectre_acl"  # stores JSON array of Discord role IDs

def get_file_acl(file_id: str) -> List[int]:
    """Return list of Discord role IDs allowed for this file."""
    service = get_drive_service()
    meta = service.files().get(
        fileId=file_id,
        fields="appProperties",
        supportsAllDrives=True,
    ).execute()
    app_props = meta.get("appProperties", {}) or {}
    raw = app_props.get(ACL_KEY)
    if not raw:
        return []
    try:
        arr = json.loads(raw)
        return [int(x) for x in arr if isinstance(x, (int, str))]
    except Exception:
        return []

def set_file_acl(file_id: str, role_ids: List[int]) -> None:
    """Overwrite allowed roles for this file."""
    service = get_drive_service()
    payload = {"appProperties": {ACL_KEY: json.dumps([int(x) for x in set(role_ids)])}}
    service.files().update(
        fileId=file_id, body=payload, fields="id", supportsAllDrives=True
    ).execute()

def add_role_to_acl(file_id: str, role_id: int) -> None:
    roles = set(get_file_acl(file_id))
    roles.add(int(role_id))
    set_file_acl(file_id, list(roles))

def remove_role_from_acl(file_id: str, role_id: int) -> None:
    roles = set(get_file_acl(file_id))
    if int(role_id) in roles:
        roles.remove(int(role_id))
    set_file_acl(file_id, list(roles))
