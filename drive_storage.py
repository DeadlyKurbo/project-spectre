import os
import json
import io
import base64
from typing import Dict, List, Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

# ====== Scopes ======
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

TOKEN_PATH = "token.json"
FOLDER_MAP_CACHE = "folder_map.json"

# Set in Railway: GDRIVE_FOLDER_ID = <id van je 'Dossiers' root-map>
ROOT_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "").strip()


def _ensure_token_file():
    """
    Als GDRIVE_CREDS_BASE64 is gezet (Railway var), schrijf token.json **altijd** weg.
    Dit voorkomt dat een oud committed token.json de boel overschrijft.
    """
    b64 = os.getenv("GDRIVE_CREDS_BASE64")
    if b64:
        try:
            raw = base64.b64decode(b64).decode("utf-8")
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(raw)
        except Exception as e:
            # Fallback: laat get_drive_service netjes falen als token ontbreekt
            print(f"[drive_storage] Failed to write token.json from env: {e}")

def get_drive_service():
    _ensure_token_file()
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError("token.json ontbreekt. Genereer een token met read-only scopes.")
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    return build("drive", "v3", credentials=creds)

def _is_folder(obj: dict) -> bool:
    return obj.get("mimeType") == "application/vnd.google-apps.folder"

def _list_children(service, parent_id: str, query_extra: str | None = None) -> List[dict]:
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

def refresh_folder_map(root_folder_id: str | None = None) -> Dict[str, dict]:
    root_id = (root_folder_id or ROOT_FOLDER_ID).strip()
    if not root_id:
        raise ValueError("GDRIVE_FOLDER_ID env var ontbreekt.")
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
        raise FileNotFoundError("folder_map.json ontbreekt. Run refresh eerst.")
    with open(FOLDER_MAP_CACHE, "r", encoding="utf-8") as fp:
        return json.load(fp)

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
