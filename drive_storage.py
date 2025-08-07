import os
import json
from typing import Dict, List

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ====== Config ======
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]
TOKEN_PATH = "token.json"
FOLDER_MAP_CACHE = "folder_map.json"

# Als je 1 hoofdmappen-structuur gebruikt voor SPECTRE:
# Zet dit naar de ID van de bovenste Drive-map (de URL heeft .../folders/<DIT_IS_DE_ID>)
ROOT_FOLDER_ID = os.getenv("GDRIVE_ROOT_FOLDER_ID", "root")


# ====== Auth / Service ======
def get_drive_service():
    """
    Build an authenticated Google Drive service using OAuth token.json.
    """
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(
            f"Missing {TOKEN_PATH}. Complete the OAuth flow locally first."
        )
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    return build("drive", "v3", credentials=creds)


# ====== Drive helpers ======
def _list_children(service, parent_id: str, mime_query: str = None) -> List[dict]:
    """
    List children of a Drive folder with optional MIME type filter.
    mime_query examples:
        "mimeType='application/vnd.google-apps.folder'"
        "mimeType!='application/vnd.google-apps.folder'"
    """
    q_parts = [f"'{parent_id}' in parents", "trashed = false"]
    if mime_query:
        q_parts.append(mime_query)
    q = " and ".join(q_parts)

    items: List[dict] = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=1000,
                pageToken=page_token,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            )
            .execute()
        )
        items.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def _is_folder(file_obj: dict) -> bool:
    return file_obj.get("mimeType") == "application/vnd.google-apps.folder"


def _strip_json(name: str) -> str:
    return name[:-5] if name.lower().endswith(".json") else name


# ====== Public API used by your bot ======
def refresh_folder_map(root_folder_id: str = None) -> Dict[str, dict]:
    """
    Scan Drive and build a 2‑level map:
        {
          "<CategoryFolderName>": {
             "id": "<category_folder_id>",
             "items": {
                 "<item_name_without_ext>": {
                     "id": "<file_id>",
                     "name": "<file_name>.json"
                 },
                 ...
             }
          },
          ...
        }

    Categories = subfolders of ROOT
    Items      = .json files directly inside each category folder

    Saves JSON to FOLDER_MAP_CACHE and returns the dict.
    """
    root_id = root_folder_id or ROOT_FOLDER_ID
    service = get_drive_service()

    try:
        # 1) Top-level: all category folders
        categories = _list_children(
            service, root_id, "mimeType='application/vnd.google-apps.folder'"
        )

        folder_map: Dict[str, dict] = {}

        for cat in categories:
            cat_name = cat["name"]
            cat_id = cat["id"]

            # 2) Inside each category: collect JSON files as items
            files = _list_children(
                service, cat_id, "mimeType!='application/vnd.google-apps.folder'"
            )

            items: Dict[str, dict] = {}
            for f in files:
                # Only track .json dossier files; skip others silently
                if not f["name"].lower().endswith(".json"):
                    continue
                item_key = _strip_json(f["name"])
                items[item_key] = {"id": f["id"], "name": f["name"]}

            folder_map[cat_name] = {"id": cat_id, "items": items}

        # 3) Cache to disk
        with open(FOLDER_MAP_CACHE, "w", encoding="utf-8") as fp:
            json.dump(folder_map, fp, indent=2, ensure_ascii=False)

        return folder_map

    except HttpError as e:
        raise RuntimeError(f"Drive API error while refreshing folder map: {e}")


def load_folder_map() -> Dict[str, dict]:
    """
    Load the cached folder map. Raises if missing.
    """
    if not os.path.exists(FOLDER_MAP_CACHE):
        raise FileNotFoundError(
            f"{FOLDER_MAP_CACHE} not found. Run refresh_folder_map() first."
        )
    with open(FOLDER_MAP_CACHE, "r", encoding="utf-8") as fp:
        return json.load(fp)
