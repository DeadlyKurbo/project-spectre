# drive_storage.py — Google Drive helpers voor DRIVE backend
import os, io, re, json, base64
from typing import Dict, List, Tuple, Optional

from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# Provide an alias so tests can patch the user credentials class.
UserCredentials = Credentials

GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")  # root map id
TOKEN_PATH = os.getenv("GDRIVE_TOKEN_PATH", "token.json")
ENV_TOKEN_JSON_B64 = "GDRIVE_TOKEN_JSON_BASE64"
ENV_TOKEN_JSON_RAW = "GDRIVE_TOKEN_JSON"

# Full Drive scope zodat bestaande files leesbaar zijn
SCOPES: List[str] = ["https://www.googleapis.com/auth/drive"]

def _load_token_info() -> Optional[dict]:
    if os.path.exists(TOKEN_PATH):
        try:
            with open(TOKEN_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    b64 = os.getenv(ENV_TOKEN_JSON_B64)
    if b64:
        try:
            padded = b64 + "=" * (-len(b64) % 4)
            return json.loads(base64.b64decode(padded).decode("utf-8"))
        except Exception:
            pass
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
        return Credentials(
            token=None,
            refresh_token=None,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GDRIVE_CLIENT_ID"),
            client_secret=os.getenv("GDRIVE_CLIENT_SECRET"),
            scopes=SCOPES,
        )
    # check scope
    scopes_in_token = tok.get("scopes") or []
    if isinstance(scopes_in_token, str):
        scopes_in_token = scopes_in_token.split()
    if "https://www.googleapis.com/auth/drive" not in scopes_in_token:
        raise RuntimeError("Token mist volledige Drive-scope. Autoriseer opnieuw met full-drive.")
    creds = Credentials.from_authorized_user_info(tok)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        try:
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": scopes_in_token,
                }, f, indent=2)
        except Exception:
            pass
    return creds

def _service():
    if not GDRIVE_FOLDER_ID:
        raise RuntimeError("GDRIVE_FOLDER_ID ontbreekt.")
    return build("drive", "v3", credentials=_get_credentials(), cache_discovery=False)

def _sanitize(name: str) -> str:
    name = re.sub(r"\.json$", "", name.strip(), flags=re.IGNORECASE)
    name = name.replace(" ", "_").replace("-", "_")
    return name.lower()

# ── folder map ─────────────────────────────
def refresh_folder_map() -> Dict:
    svc = _service()
    q = f"'{GDRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    cats, page = [], None
    while True:
        resp = svc.files().list(q=q, fields="nextPageToken, files(id,name)", pageToken=page, pageSize=1000).execute()
        cats += resp.get("files", [])
        page = resp.get("nextPageToken")
        if not page: break

    folder_map: Dict[str, Dict] = {}
    for c in cats:
        cat_id = c["id"]
        cat_key = _sanitize(c["name"])
        folder_map.setdefault(cat_key, {"id": cat_id, "items": {}})

        q2 = f"'{cat_id}' in parents and trashed=false and (mimeType='application/json' or name contains '.json')"
        page2 = None
        while True:
            resp2 = svc.files().list(q=q2, fields="nextPageToken, files(id,name,mimeType)", pageToken=page2, pageSize=1000).execute()
            for f in resp2.get("files", []):
                item_key = _sanitize(f["name"])
                folder_map[cat_key]["items"][item_key] = {"id": f["id"], "name": f["name"]}
            page2 = resp2.get("nextPageToken")
            if not page2: break
    # cache lokaal (optioneel)
    with open("folder_map.json", "w", encoding="utf-8") as fp:
        json.dump(folder_map, fp, indent=2, ensure_ascii=False)
    return folder_map

def load_folder_map() -> Dict:
    if os.path.exists("folder_map.json"):
        try:
            with open("folder_map.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return refresh_folder_map()

# ── dossiers ───────────────────────────────
def fetch_dossier_json(file_id: str):
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
        return {"_raw": raw}, raw

def _ensure_category_folder(category: str) -> str:
    svc = _service()
    cat_name = category.replace("_", " ").title()
    q = f"'{GDRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and name='{cat_name}' and trashed=false"
    resp = svc.files().list(q=q, fields="files(id,name)").execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    body = {
        "name": cat_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [GDRIVE_FOLDER_ID],
    }
    folder = svc.files().create(body=body, fields="id").execute()
    return folder["id"]

def create_json_file(category: str, item: str, content: str) -> str:
    """Maak of overschrijf `<category>/<item>.json` in Drive."""
    svc = _service()
    cat_id = _ensure_category_folder(category)
    name = f"{item}.json"
    # check of bestaat
    q = f"'{cat_id}' in parents and name='{name}' and trashed=false"
    resp = svc.files().list(q=q, fields="files(id)").execute()
    media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype="application/json", resumable=False)
    if resp.get("files"):
        fid = resp["files"][0]["id"]
        svc.files().update(fileId=fid, media_body=media).execute()
        return fid
    metadata = {"name": name, "parents": [cat_id], "mimeType": "application/json"}
    file = svc.files().create(body=metadata, media_body=media, fields="id").execute()
    return file["id"]

# ── ACL via appProperties ──────────────────
def _get_meta(file_id: str) -> dict:
    return _service().files().get(fileId=file_id, fields="id,name,appProperties").execute()

def get_file_acl(file_id: str):
    props = (_get_meta(file_id).get("appProperties")) or {}
    raw = props.get("acl_roles")
    if not raw: return []
    try:
        arr = json.loads(raw); return [int(x) for x in arr]
    except Exception:
        try:
            return [int(x) for x in str(raw).split(",") if x.strip()]
        except Exception:
            return []

def _write_acl(file_id: str, role_ids):
    props = {"acl_roles": json.dumps([int(x) for x in role_ids])}
    _service().files().update(fileId=file_id, body={"appProperties": props}).execute()

def add_role_to_acl(file_id: str, role_id: int):
    roles = set(get_file_acl(file_id)); roles.add(int(role_id)); _write_acl(file_id, sorted(roles))

def remove_role_from_acl(file_id: str, role_id: int):
    roles = set(get_file_acl(file_id))
    if int(role_id) in roles:
        roles.remove(int(role_id))
        _write_acl(file_id, sorted(roles))


# --- Compatibility helpers -------------------------------------------------
#
# Some parts of the project – notably the unit tests – rely on a minimal set of
# helper functions that existed before the large refactor of this module.  The
# refactor removed these helpers which left the tests (and any external code
# using them) without an easy way to interact with Google Drive.  Re-introduce
# lightweight versions of the old helpers so that callers can obtain a Drive
# service and upload/download JSON files without needing the full folder map
# machinery above.


def get_drive_service():
    """Return a Google Drive service instance using available credentials.

    The function looks for credentials in the following order:

    1. A token file pointed to by ``GDRIVE_TOKEN_FILE`` containing user
       credentials.
    2. A base64 encoded service account JSON in ``GDRIVE_CREDS_BASE64``.
    3. A path to a service account JSON file in ``GDRIVE_CREDS_FILE``.

    This mirrors the behaviour expected by the tests and provides a graceful
    fallback sequence so that a missing or invalid token file does not prevent
    service account credentials from being used instead.
    """

    token_path = os.getenv("GDRIVE_TOKEN_FILE")
    creds = None

    if token_path and os.path.exists(token_path):
        try:
            info = json.loads(open(token_path, "r", encoding="utf-8").read())
            creds = UserCredentials.from_authorized_user_info(info, scopes=SCOPES)
        except Exception:
            creds = None

    if creds is None:
        b64 = os.getenv("GDRIVE_CREDS_BASE64")
        file_path = os.getenv("GDRIVE_CREDS_FILE")
        try:
            if b64:
                info = json.loads(base64.b64decode(b64).decode("utf-8"))
                creds = ServiceAccountCredentials.from_service_account_info(
                    info, scopes=SCOPES
                )
            elif file_path and os.path.exists(file_path):
                creds = ServiceAccountCredentials.from_service_account_file(
                    file_path, scopes=SCOPES
                )
        except Exception:
            creds = None

    if creds is None:
        raise RuntimeError("No Google Drive credentials found")

    return build("drive", "v3", credentials=creds)


def upload_json(filename: str, data: dict, *, folder_id: str | None = None, service=None) -> str:
    """Upload ``data`` as JSON to Google Drive and return the file id."""

    service = service or get_drive_service()
    body = {"name": filename}
    if folder_id:
        body["parents"] = [folder_id]
    media = MediaIoBaseUpload(
        io.BytesIO(json.dumps(data).encode("utf-8")),
        mimetype="application/json",
        resumable=False,
    )
    resp = service.files().create(body=body, media_body=media).execute()
    return resp.get("id")


def download_json(file_id: str, *, service=None):
    """Download a JSON file from Google Drive and return its contents."""

    service = service or get_drive_service()
    raw = service.files().get(fileId=file_id, alt="media").execute()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)
