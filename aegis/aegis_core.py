"""Shared AEGIS logic: config, paths, portal API. No UI dependencies."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from aegis.chat_store import load_messages, save_message
except ImportError:
    from chat_store import load_messages, save_message

_REFRESH_INTERVAL_MS = 2000


@dataclass(frozen=True)
class AegisConfig:
    operator_name: str
    create_desktop_shortcut: bool
    portal_base: str = ""
    account_name: str = ""
    password: str = ""


def default_operator_name() -> str:
    return os.getenv("AEGIS_OPERATOR_NAME", os.getenv("USERNAME", "")).strip() or "Operator"


def resolve_assets_dir() -> Path:
    """Resolve assets directory (frozen EXE extracts to _MEIPASS)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parent / "assets"


def resolve_install_dir() -> Path:
    """Resolve the AEGIS install directory (for config, shortcuts, etc.)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    argv_path = Path(sys.argv[0])
    if argv_path.exists():
        if argv_path.is_dir():
            return argv_path.resolve()
        argv_parent = argv_path.resolve().parent
        if argv_parent.name == "dist" and (argv_parent.parent / "aegis_app.py").exists():
            return argv_parent.parent
        return argv_parent
    return Path(__file__).resolve().parent


def _quote_windows_argument(value: str) -> str:
    if not value:
        return value
    if any(char.isspace() for char in value):
        return f'"{value}"'
    return value


def config_path() -> Path:
    if getattr(sys, "frozen", False) and platform.system() == "Windows":
        base = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        return Path(base) / "AEGIS" / "aegis-config.json"
    install_dir = resolve_install_dir()
    path = install_dir / "aegis-config.json"
    if os.access(install_dir, os.W_OK):
        return path
    return Path.home() / ".aegis-config.json"


def load_config(path: Path) -> Optional[AegisConfig]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return AegisConfig(
        operator_name=data.get("operator_name", default_operator_name()).strip() or default_operator_name(),
        create_desktop_shortcut=bool(data.get("create_desktop_shortcut", False)),
        portal_base=(data.get("portal_base") or "").strip(),
        account_name=(data.get("account_name") or "").strip(),
        password=(data.get("password") or "").strip(),
    )


def save_config(path: Path, config: AegisConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "operator_name": config.operator_name,
        "create_desktop_shortcut": config.create_desktop_shortcut,
        "portal_base": config.portal_base,
        "account_name": config.account_name,
        "password": config.password,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _create_windows_shortcut(shortcut_path: Path, target_path: Path, working_dir: Path, arguments: str = "") -> None:
    escaped_shortcut = str(shortcut_path).replace("'", "''")
    escaped_target = str(target_path).replace("'", "''")
    escaped_workdir = str(working_dir).replace("'", "''")
    escaped_args = arguments.replace("'", "''")
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{shortcut}');"
        "$s.TargetPath='{target}';"
        "$s.WorkingDirectory='{workdir}';"
        "{args}"
        "$s.WindowStyle=1;"
        "$s.Description='Launch the A.E.G.I.S. operator console';"
        "$s.Save();"
    ).format(
        shortcut=escaped_shortcut,
        target=escaped_target,
        workdir=escaped_workdir,
        args=f"$s.Arguments='{escaped_args}';" if escaped_args else "",
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_desktop_shortcut(config: AegisConfig) -> None:
    if not config.create_desktop_shortcut:
        return
    if platform.system().lower() != "windows":
        return
    install_dir = resolve_install_dir()
    venv_scripts = install_dir / ".venv" / "Scripts"
    pythonw = venv_scripts / "pythonw.exe"
    python_exe = venv_scripts / "python.exe"
    launcher = pythonw if pythonw.exists() else (python_exe if python_exe.exists() else Path(sys.executable))
    if getattr(sys, "frozen", False):
        arguments = ""
    else:
        arguments = _quote_windows_argument(str(install_dir / "aegis_app.py"))
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / "A.E.G.I.S. Welcome.lnk"
    if shortcut_path.exists():
        return
    _create_windows_shortcut(shortcut_path, launcher, install_dir, arguments=arguments)


def desktop_shortcut_exists() -> bool:
    if platform.system().lower() != "windows":
        return False
    return (Path.home() / "Desktop" / "A.E.G.I.S. Welcome.lnk").exists()


def portal_login(portal_base: str, account_name: str, password: str) -> Optional[str]:
    if not portal_base or not account_name or not password:
        return None
    url = f"{portal_base.rstrip('/')}/api/aegis/chat/login"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"account_name": account_name, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("token") or None
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def portal_fetch_messages(portal_base: str, token: str) -> list:
    if not portal_base or not token:
        return []
    url = f"{portal_base.rstrip('/')}/api/aegis/chat/messages"
    try:
        req = urllib.request.Request(url, headers={"X-Aegis-Token": token}, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            messages = data.get("messages") or []
            return messages if isinstance(messages, list) else []
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError):
        return []


def portal_send_message(portal_base: str, token: str, message: str) -> bool:
    if not portal_base or not token or not message.strip():
        return False
    url = f"{portal_base.rstrip('/')}/api/aegis/chat/messages"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"message": message.strip()}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Aegis-Token": token},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return False
