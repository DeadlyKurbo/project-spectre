from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import server_config

app = FastAPI(title="SPECTRE Config Service")

# Basic auth credentials sourced from environment variables.
_ADMIN_USER = os.getenv("DASHBOARD_USERNAME", "admin")
_ADMIN_PASS = os.getenv("DASHBOARD_PASSWORD", "password")
_security = HTTPBasic()

CONFIG_FILE = Path(__file__).resolve().parent / "server_configs.json"


def _authenticate(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    """Validate basic auth credentials.

    Raises ``HTTPException`` with 401 status if authentication fails.
    """

    correct_user = secrets.compare_digest(credentials.username, _ADMIN_USER)
    correct_pass = secrets.compare_digest(credentials.password, _ADMIN_PASS)
    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.get("/configs", dependencies=[Depends(_authenticate)])
async def list_configs() -> Dict[str, Dict[str, Any]]:
    """Return the full mapping of guild configurations."""

    server_config.reload_server_configs()
    return {str(gid): cfg.settings for gid, cfg in server_config.SERVER_CONFIGS.items()}


@app.get("/configs/{guild_id}", dependencies=[Depends(_authenticate)])
async def get_config(guild_id: int) -> Dict[str, Any]:
    """Return configuration for ``guild_id``."""

    cfg = server_config.get_server_config(guild_id)
    return cfg.settings


@app.put("/configs/{guild_id}", dependencies=[Depends(_authenticate)])
async def update_config(guild_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``payload`` into the configuration for ``guild_id`` and persist."""

    data: Dict[str, Dict[str, Any]] = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Invalid configuration file")

    guild_key = str(guild_id)
    current = data.get(guild_key, {})
    current.update(payload)
    data[guild_key] = current

    CONFIG_FILE.write_text(json.dumps(data, indent=4, sort_keys=True))
    server_config.reload_server_configs()
    return current
