#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

DATA_ROOT = Path("data/guilds")

def _gdir(guild_id: int) -> Path:
    p = DATA_ROOT / str(guild_id)
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

# -------- Public API --------

def get_config(guild_id: int) -> Dict[str, Any]:
    """Returns config for a guild, with safe defaults."""
    cfg_path = _gdir(guild_id) / "config.json"
    cfg = _load_json(cfg_path)
    # defaults
    cfg.setdefault("archive_name", None)        # shown in embeds; None → fallback
    cfg.setdefault("archive_channel_id", None)  # int or None
    return cfg

def set_config(guild_id: int, **updates: Any) -> Dict[str, Any]:
    cfg_path = _gdir(guild_id) / "config.json"
    cfg = get_config(guild_id)
    cfg.update({k: v for k, v in updates.items() if v is not None})
    _save_json(cfg_path, cfg)
    return cfg

def get_anchor(guild_id: int) -> Optional[Tuple[int, int]]:
    """Return (channel_id, message_id) for the archive menu message if exists."""
    path = _gdir(guild_id) / "anchor.json"
    data = _load_json(path)
    if not data:
        return None
    try:
        return int(data["channel_id"]), int(data["message_id"])
    except Exception:
        return None

def set_anchor(guild_id: int, channel_id: int, message_id: int) -> None:
    path = _gdir(guild_id) / "anchor.json"
    _save_json(path, {"channel_id": int(channel_id), "message_id": int(message_id)})

def clear_anchor(guild_id: int) -> None:
    path = _gdir(guild_id) / "anchor.json"
    try:
        path.unlink(missing_ok=True)  # py3.8+: ignore if missing
    except Exception:
        pass
