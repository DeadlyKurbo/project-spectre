#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

DATA_ROOT = Path("data/guilds")

def _gdir(gid: int) -> Path:
    p = DATA_ROOT / str(gid)
    p.mkdir(parents=True, exist_ok=True)
    return p

def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

# ---- Config ----
def get_config(gid: int) -> Dict[str, Any]:
    cfg = _load_json(_gdir(gid) / "config.json")
    cfg.setdefault("archive_name", None)
    cfg.setdefault("archive_channel_id", None)
    return cfg

def set_config(gid: int, **updates: Any) -> Dict[str, Any]:
    p = _gdir(gid) / "config.json"
    cfg = get_config(gid)
    for k, v in updates.items():
        cfg[k] = v
    _save_json(p, cfg)
    return cfg

# ---- Anchor (message location) ----
def get_anchor(gid: int) -> Optional[Tuple[int, int]]:
    d = _load_json(_gdir(gid) / "anchor.json")
    if not d: return None
    try:
        return int(d["channel_id"]), int(d["message_id"])
    except Exception:
        return None

def set_anchor(gid: int, ch_id: int, msg_id: int) -> None:
    _save_json(_gdir(gid) / "anchor.json", {"channel_id": int(ch_id), "message_id": int(msg_id)})

def clear_anchor(gid: int) -> None:
    f = _gdir(gid) / "anchor.json"
    try: f.unlink(missing_ok=True)
    except Exception: pass

# ---- Deploy trigger (website -> bot) ----
def request_deploy(gid: int, reason: str = "dashboard") -> None:
    _save_json(_gdir(gid) / "deploy.json", {"requested": True, "ts": time.time(), "reason": reason})

def take_deploy_requests() -> List[int]:
    """Return list of guild_ids that requested deploy and clear the flag."""
    gids: List[int] = []
    for gdir in DATA_ROOT.glob("*"):
        if not gdir.is_dir(): continue
        f = gdir / "deploy.json"
        if f.exists():
            gids.append(int(gdir.name))
            try: f.unlink()
            except Exception: pass
    return gids
