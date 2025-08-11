# drive_storage.py
# Compat-layer voor Project SPECTRE:
# - OAuth met token.json (of env fallback)
# - Folder map scan (categorie -> items)
# - Dossier fetch (JSON)
# - ACL via Drive appProperties
# - SCOPES export voor /debugdrive (FULL DRIVE)

import os
import io
import re
import json
from typing import Dict, List, Tuple, Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# === CONFIG / ENV ===========================================================
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")  # root van jouw archief (verplicht)

# token.json pad (default: cwd/token.json). Mag ook via env base64/raw.
TOKEN_PATH = os.getenv("GDRIVE_TOKEN_PATH", "token.json")
ENV_TOKEN_JSON_B64 = "GDRIVE_TOKEN_JSON_BASE64"
ENV_TOKEN_JSON_RAW = "GDRIVE_TOKEN_JSON"

# *** Vereist: volledige Drive-toegang zodat ALLE bestaande files werken ***
SCOPES: List[str] = ["https://www.googleapis.com/auth/drive"]

# === HULP ===================================================================
def _load_token_info() -> Optional[dict]:
    # 1) file token.json
    if os.path.exists(TOKEN_PATH):
        try:
            with open(TOKEN_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # 2) env base64
    b64 = os.getenv(ENV_TOKEN_JSON_B64)
    if b64:
        import base64
        try:
            return json.loads(base64.b64decode(b64).decode("utf-8"))
        except Exception:
            pass
    # 3) env raw
    raw = os.getenv(ENV_TOKEN_JSON_RAW)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return None


def _get_credentials() -> Credentials:
    tok = _load_token_info()
    if not tok:
        # Geen token aanwezig → lege Credentials met gewenste FULL-DRIVE scopes.
        return Credentials(
            token=None,
            refresh_token=None,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GDRIVE_CLIENT_ID"),
            client_secret=os.getenv("GDRIVE_CLIENT_SECRET"),
            scopes=SCOPES,
        )

    # Gebruik exact de token-gegevens (en check of scope voldoende is)
    creds = Credentials.from_authorized_user_info(tok)

    # Scope-check: zonder full-drive krijg je 403 'appNotAuthorizedToFile'
    scopes_in_token = tok.get("scopes") or []
    if isinstance(scopes_in_token, str):
        scopes_in_token = scopes_in_token.split()
    if "https://www.googleapis.com/auth/drive" not in scopes_in_token:
        raise RuntimeError(
            "Token heeft geen volledige Drive-scope. "
            "Run /authlink en autoriseer opnieuw (verwijder eerst token.json/Railway token vars)."
        )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Optioneel: vernieuwde token terugschrijven
        try:
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                info = {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": scopes_in_token,
                }
                json.dump(info, f, indent=2)
        except Exception:
            pass
    return creds


def _service():
    if not GDRIVE_FOLDER_ID:
        raise RuntimeError("GDRIVE_FOLDER_ID is niet gezet.")
    return build("drive", "v3", credentials=_get_credentials(), cache_discovery=False)


def _sanitize(name: str) -> str:
    # Normaliseer naar jouw key-stijl in UI (lowercase, underscores, zonder .json)
    name = name.strip()
    name = re.sub(r"\.json$", "", name, flags=re.IGNORECASE)
    name = name.replace(" ", "_").replace("-", "_")
    return name.lower()


# === FOLDER MAP =============================================================
def refresh_folder_map() -> Dict:
    """
    Scan root (GDRIVE_FOLDER_ID):
      - subfolders = categorieën
      - in elke categorie: *.json -> items
    Returnt dict: { category: { "id": <folderId>, "items": { item: { "id": <fileId>, "name": <orig> } } } }
    """
    svc = _service()

    # 1) categorie-mappen in root
    q = f"'{GDRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    cats = []
    page = None
    while True:
        resp = svc.files().list(
            q=q, fields="nextPageToken, files(id,name)", pageToken=page, pageSize=1000
        ).execute()
        cats.extend(resp.get("files", []))
        page = resp.get("nextPageToken")
        if not page:
            break

    folder_map: Dict[str, Dict] = {}

    for c in cats:
        cat_id = c["id"]
        cat_key = _sanitize(c["name"])
        folder_map.setdefault(cat_key, {"id": cat_id, "items": {}})

        # 2) items (json) per categorie
        q2 = (
            f"'{cat_id}' in parents and trashed=false and "
            f"(mimeType='application/json' or name contains '.json')"
        )
        page2 = None
        while True:
            resp2 = svc.files().list(
                q=q2,
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page2,
                pageSize=1000,
            ).execute()
            for f in resp2.get("files", []):
                fname = f["name"]
                item_key = _sanitize(fname)
                folder_map[cat_key]["items"][item_key] = {
                    "id": f["id"],
                    "name": fname,
                }
            page2 = resp2.get("nextPageToken")
            if not page2:
                break

    return folder_map


def load_folder_map() -> Dict:
    """
    Leest lokale folder_map.json als die er is, anders bouwt live via Drive.
    (Jouw main.py schrijft bij /refresh zelf naar folder_map.json.)
    """
    path = "folder_map.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return refresh_folder_map()


# === DOSSIERS ===============================================================
def fetch_dossier_json(file_id: str) -> Tuple[Dict, str]:
    """
    Download JSON file body. Return (dict_data, pretty_str).
    Als de content geen geldige JSON is, wrap het als {"_raw": <text>}.
    """
    svc = _service()
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    raw = buf.read().decode("utf-8", errors="replace")

    try:
        data = json.loads(raw)
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        return data, pretty
    except Exception:
        data = {"_raw": raw}
        return data, raw


# === ACL via appProperties ==================================================
# We bewaren een string property "acl_roles" met als value een JSON array van ints.
# appProperties zijn per-file, blijven bestaan, en zijn alleen zichtbaar voor de app/user.

def _get_file_meta(file_id: str) -> dict:
    svc = _service()
    return svc.files().get(fileId=file_id, fields="id, name, appProperties").execute()


def get_file_acl(file_id: str) -> List[int]:
    meta = _get_file_meta(file_id)
    props = (meta or {}).get("appProperties") or {}
    raw = props.get("acl_roles")
    if not raw:
        return []
    try:
        arr = json.loads(raw)
        return [int(x) for x in arr]
    except Exception:
        # fallback comma-gescheiden
        try:
            return [int(x) for x in str(raw).split(",") if x.strip()]
        except Exception:
            return []


def _write_acl(file_id: str, role_ids: List[int]) -> None:
    svc = _service()
    props = {"acl_roles": json.dumps([int(x) for x in role_ids])}
    svc.files().update(fileId=file_id, body={"appProperties": props}).execute()


def add_role_to_acl(file_id: str, role_id: int) -> None:
    roles = set(get_file_acl(file_id))
    roles.add(int(role_id))
    _write_acl(file_id, sorted(roles))


def remove_role_from_acl(file_id: str, role_id: int) -> None:
    roles = set(get_file_acl(file_id))
    if int(role_id) in roles:
        roles.remove(int(role_id))
        _write_acl(file_id, sorted(roles))
