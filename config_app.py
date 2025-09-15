import os
import json
import logging
from secrets import compare_digest

from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from storage_spaces import read_json, write_json, backup_json


logger = logging.getLogger(__name__)

app = FastAPI()
auth = HTTPBasic()


def _env_or_default(key: str, default: str) -> str:
    value = os.getenv(key)
    if value is None:
        logger.warning("%s not set; defaulting to %r", key, default)
        return default
    return value


ADMIN_USER = _env_or_default("DASHBOARD_USERNAME", "admin")
ADMIN_PASS = _env_or_default("DASHBOARD_PASSWORD", "password")


def require_auth(creds: HTTPBasicCredentials = Depends(auth)):
    if not (
        compare_digest(creds.username, ADMIN_USER)
        and compare_digest(creds.password, ADMIN_PASS)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

@app.get("/health")
async def health():
    return {"ok": True}

def guild_key(guild_id: str) -> str:
    return f"guild-configs/{guild_id}.json"

@app.get("/configs/{guild_id}")
async def get_guild_config(guild_id: str, _: bool = Depends(require_auth)):
    doc, etag = read_json(guild_key(guild_id), with_etag=True)
    if not doc:
        return JSONResponse({"_meta": {"etag": None}, "settings": {}}, status_code=200)
    doc["_meta"] = {"etag": etag}
    return JSONResponse(doc)

@app.put("/configs/{guild_id}")
async def put_guild_config(guild_id: str, request: Request, _: bool = Depends(require_auth)):
    payload = await request.json()

    current, etag = read_json(guild_key(guild_id), with_etag=True)
    if current:
        backup_json(guild_key(guild_id).split("/")[-1], current)

    client_etag = (payload.get("_meta") or {}).get("etag")
    to_store = {k: v for k, v in payload.items() if k != "_meta"}
    ok = write_json(guild_key(guild_id), to_store, etag=client_etag or etag)
    if not ok:
        raise HTTPException(status_code=409, detail="Config changed on server; refresh and retry.")
    return {"ok": True}
