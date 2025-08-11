# drive_storage.py
# Drop-in Google Drive OAuth helper voor jouw bot (Nextcord/any).
# Lost "invalid_scope" op door exact de token-scopes te gebruiken zodra een token aanwezig is.

import os
import json
import base64
from typing import Dict, List, Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- CONFIG ---------------------------------------------------------------

# Scopes die we willen gebruiken ALS er nog géén token bestaat.
# (Dit is wat je nu al hebt in je token: drive.file + drive.metadata.readonly)
DESIRED_SCOPES: List[str] = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

# Omgevingsvariabelen (Railway/locaal)
ENV_CLIENT_BASE64 = "GDRIVE_CREDS_BASE64"       # base64 van je OAuth client (client_id/client_secret/…)
ENV_CLIENT_JSON   = "GDRIVE_CREDS"              # raw JSON string (fallback)
ENV_TOKEN_BASE64  = "GDRIVE_TOKEN_JSON_BASE64"  # base64 van token.json (refresh_token etc.)
ENV_TOKEN_JSON    = "GDRIVE_TOKEN_JSON"         # raw JSON string (fallback)

# -------------------------------------------------------------------------


def _maybe_b64_to_json(s: Optional[str]) -> Optional[Dict]:
    if not s:
        return None
    s = s.strip().strip('"').strip("'")
    try:
        # Probeer base64
        decoded = base64.b64decode(s)
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        pass
    try:
        # Probeer direct JSON
        return json.loads(s)
    except Exception:
        return None


def _load_client_info() -> Dict:
    data = _maybe_b64_to_json(os.getenv(ENV_CLIENT_BASE64)) or _maybe_b64_to_json(os.getenv(ENV_CLIENT_JSON))
    if not data:
        raise RuntimeError("Google OAuth client credentials ontbreken. Zet GDRIVE_CREDS_BASE64 of GDRIVE_CREDS.")
    return data


def _load_token_info() -> Optional[Dict]:
    data = _maybe_b64_to_json(os.getenv(ENV_TOKEN_BASE64)) or _maybe_b64_to_json(os.getenv(ENV_TOKEN_JSON))
    return data


def get_credentials() -> Credentials:
    """
    Laadt credentials.
    - Als token aanwezig: gebruik PRECIÉS die scopes uit het token (voorkomt invalid_scope).
    - Als geen token: maak Credentials container met gewenste scopes (géén auth flow hier).
    """
    client_info = _load_client_info()
    token_info = _load_token_info()

    if token_info:
        # Gebruik scopes zoals vastgelegd in het token (belangrijk!)
        token_scopes = token_info.get("scopes")
        if isinstance(token_scopes, str):
            token_scopes = [token_scopes]
        # Credentials laden zonder nieuwe scopes te forceren
        creds = Credentials.from_authorized_user_info(info=token_info)
    else:
        # Nog géén token – we maken een lege Credentials met gewenste scopes (voor later exchange/refresh)
        # Let op: zonder token kun je nog géén Drive-calls doen. Je bot verwacht hier doorgaans al een token.
        creds = Credentials(
            token=None,
            refresh_token=None,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_info.get("installed", {}).get("client_id") or client_info.get("web", {}).get("client_id"),
            client_secret=client_info.get("installed", {}).get("client_secret") or client_info.get("web", {}).get("client_secret"),
            scopes=DESIRED_SCOPES,
        )

    # Refresh indien nodig (met bestaande scopes van het token)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return creds


def get_drive_service():
    """
    Retourneert een geauthenticeerde Drive service.
    Gooit een duidelijke fout als scopes/token niet kloppen.
    """
    creds = get_credentials()
    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return service
    except HttpError as e:
        # Geef nettere melding door
        raise RuntimeError(f"Google Drive HttpError: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Kon Drive service niet bouwen: {e}") from e


# ====== Handige helpers voor je bot ======

def debug_dump() -> str:
    """
    Geeft een string met nuttige debug-info om in je /debugdrive en /debugtoken te tonen.
    """
    client_present = _load_client_info() is not None
    token_info = _load_token_info()
    token_present = token_info is not None
    token_scopes = token_info.get("scopes", []) if token_info else []
    if isinstance(token_scopes, str):
        token_scopes = [token_scopes]

    lines = []
    lines.append("drive_storage.SCOPES (desired if no token):")
    lines.append(json.dumps(DESIRED_SCOPES, indent=2))
    lines.append("")
    lines.append(f"{ENV_CLIENT_BASE64 or ENV_CLIENT_JSON} present: {client_present}")
    lines.append(f"token.json present: {token_present}")
    if token_present:
        lines.append("scopes in token.json:")
        lines.append(json.dumps(token_scopes, indent=2))
        lines.append(f"client_id in token.json: {token_info.get('client_id', '—')}")
    return "\n".join(lines)


def upload_json(drive_folder_id: str, filename: str, data: Dict) -> str:
    """
    Upload/overschrijf een JSON-bestand.
    Vereist dat je token toegang heeft tot de folder (met drive.file is dit oké voor bestanden die jouw app maakt).
    """
    service = get_drive_service()

    # Bestaat het bestand al?
    query = f"'{drive_folder_id}' in parents and name = '{filename}' and mimeType='application/json' and trashed = false"
    res = service.files().list(q=query, fields="files(id,name)").execute()
    files = res.get("files", [])

    media_body = json.dumps(data).encode("utf-8")

    from googleapiclient.http import MediaIoBaseUpload
    import io
    media = MediaIoBaseUpload(io.BytesIO(media_body), mimetype="application/json", resumable=False)

    if files:
        file_id = files[0]["id"]
        service.files().update(fileId=file_id, media_body=media).execute()
        return file_id
    else:
        file_metadata = {"name": filename, "parents": [drive_folder_id]}
        created = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        return created["id"]


def download_json(file_id: str) -> Dict:
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    from googleapiclient.http import MediaIoBaseDownload
    import io
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return json.loads(fh.read().decode("utf-8"))


if __name__ == "__main__":
    # Lokaal snel testen:
    print(debug_dump())
