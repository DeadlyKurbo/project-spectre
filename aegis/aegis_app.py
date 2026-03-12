"""Standalone UI launcher for the A.E.G.I.S. operator console.

Running this module opens a Discord-style window with a built-in operator chat.
Messages are stored locally—no server connection required.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import tkinter as tk
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Tuple

try:
    from aegis.chat_store import load_messages, save_message
except ImportError:
    from chat_store import load_messages, save_message

# Military / sci-fi command console palette
_BG_MAIN: str = "#0D1117"          # Near-black base
_BG_SIDEBAR: str = "#161B22"        # Dark grey panels
_BG_DARK: str = "#0D1117"           # Darkest
_BG_INPUT: str = "#21262D"          # Input field
_ACCENT: str = "#0096FF"            # Neon blue
_ACCENT_HOVER: str = "#58B4FF"
_TEXT: str = "#E6EDF3"
_TEXT_MUTED: str = "#8B949E"
_ONLINE: str = "#3FB950"
_WINDOW_PADDING: Tuple[int, int] = (0, 0)
_REFRESH_INTERVAL_MS = 2000     # Refresh messages from store
_MAX_MESSAGES = 500             # Prune older messages


@dataclass(frozen=True)
class AegisConfig:
    operator_name: str
    create_desktop_shortcut: bool
    portal_base: str = ""
    account_name: str = ""
    password: str = ""


def _default_operator_name() -> str:
    return os.getenv("AEGIS_OPERATOR_NAME", os.getenv("USERNAME", "")).strip() or "Operator"


def _resolve_assets_dir() -> Path:
    """Resolve assets directory (frozen EXE extracts to _MEIPASS)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parent / "assets"


def _resolve_install_dir() -> Path:
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


def _resolve_windows_launcher(install_dir: Path) -> Path:
    venv_scripts = install_dir / ".venv" / "Scripts"
    pythonw = venv_scripts / "pythonw.exe"
    if pythonw.exists():
        return pythonw
    python = venv_scripts / "python.exe"
    if python.exists():
        return python
    return Path(sys.executable)


def _quote_windows_argument(value: str) -> str:
    if not value:
        return value
    if any(char.isspace() for char in value):
        return f'"{value}"'
    return value


def _config_path() -> Path:
    # When frozen (portable EXE), always use AppData so config persists regardless of exe location
    if getattr(sys, "frozen", False) and platform.system() == "Windows":
        base = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        return Path(base) / "AEGIS" / "aegis-config.json"
    install_dir = _resolve_install_dir()
    config_path = install_dir / "aegis-config.json"
    if os.access(install_dir, os.W_OK):
        return config_path
    return Path.home() / ".aegis-config.json"


def _load_config(path: Path) -> Optional[AegisConfig]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return AegisConfig(
        operator_name=data.get("operator_name", _default_operator_name()).strip() or _default_operator_name(),
        create_desktop_shortcut=bool(data.get("create_desktop_shortcut", False)),
        portal_base=(data.get("portal_base") or "").strip(),
        account_name=(data.get("account_name") or "").strip(),
        password=(data.get("password") or "").strip(),
    )


def _save_config(path: Path, config: AegisConfig) -> None:
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


def _ensure_desktop_shortcut(config: AegisConfig) -> None:
    if not config.create_desktop_shortcut:
        return
    if platform.system().lower() != "windows":
        return

    install_dir = _resolve_install_dir()
    launcher = _resolve_windows_launcher(install_dir)
    if getattr(sys, "frozen", False):
        arguments = ""
    else:
        launch_target = install_dir / "aegis_app.py"
        arguments = _quote_windows_argument(str(launch_target))
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / "A.E.G.I.S. Welcome.lnk"

    if shortcut_path.exists():
        return
    _create_windows_shortcut(shortcut_path, launcher, install_dir, arguments=arguments)


def _desktop_shortcut_exists() -> bool:
    if platform.system().lower() != "windows":
        return False
    shortcut_path = Path.home() / "Desktop" / "A.E.G.I.S. Welcome.lnk"
    return shortcut_path.exists()


def _configuration_window(existing: Optional[AegisConfig]) -> Optional[AegisConfig]:
    root = tk.Tk(className="A.E.G.I.S. Configuration")
    root.title("A.E.G.I.S. Configuration")
    root.configure(bg=_BG_MAIN)

    operator_name = _default_operator_name()
    create_shortcut = not _desktop_shortcut_exists()
    portal_base = ""
    account_name = ""
    password = ""

    if existing:
        operator_name = existing.operator_name
        create_shortcut = existing.create_desktop_shortcut
        portal_base = existing.portal_base
        account_name = existing.account_name
        password = existing.password

    header = tk.Label(
        root,
        text="Configure A.E.G.I.S.",
        fg=_TEXT,
        bg=_BG_MAIN,
        font=("Segoe UI", 18, "bold"),
    )
    header.pack(pady=(24, 8))

    subtitle = tk.Label(
        root,
        text="Display name and portal credentials for mirrored ALICE chat.",
        fg=_TEXT_MUTED,
        bg=_BG_MAIN,
        font=("Segoe UI", 10),
    )
    subtitle.pack(pady=(0, 20))

    form = tk.Frame(root, bg=_BG_MAIN)
    form.pack(padx=32, pady=(0, 16), fill=tk.BOTH)

    tk.Label(form, text="Display name", fg=_TEXT_MUTED, bg=_BG_MAIN, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
    name_entry = tk.Entry(form, fg=_TEXT, bg=_BG_INPUT, insertbackground=_TEXT, relief=tk.FLAT, font=("Segoe UI", 12))
    name_entry.insert(0, operator_name)
    name_entry.pack(fill=tk.X, ipady=8, ipadx=12, pady=(0, 12))

    tk.Label(form, text="Portal URL (e.g. https://yoursite.com)", fg=_TEXT_MUTED, bg=_BG_MAIN, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
    portal_entry = tk.Entry(form, fg=_TEXT, bg=_BG_INPUT, insertbackground=_TEXT, relief=tk.FLAT, font=("Segoe UI", 12))
    portal_entry.insert(0, portal_base)
    portal_entry.pack(fill=tk.X, ipady=8, ipadx=12, pady=(0, 12))

    tk.Label(form, text="Account name (operator ID)", fg=_TEXT_MUTED, bg=_BG_MAIN, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
    account_entry = tk.Entry(form, fg=_TEXT, bg=_BG_INPUT, insertbackground=_TEXT, relief=tk.FLAT, font=("Segoe UI", 12))
    account_entry.insert(0, account_name)
    account_entry.pack(fill=tk.X, ipady=8, ipadx=12, pady=(0, 12))

    tk.Label(form, text="Password", fg=_TEXT_MUTED, bg=_BG_MAIN, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
    password_entry = tk.Entry(form, fg=_TEXT, bg=_BG_INPUT, insertbackground=_TEXT, relief=tk.FLAT, font=("Segoe UI", 12), show="*")
    password_entry.insert(0, password)
    password_entry.pack(fill=tk.X, ipady=8, ipadx=12, pady=(0, 20))

    shortcut_var = tk.BooleanVar(value=create_shortcut)
    shortcut_frame = tk.Frame(root, bg=_BG_MAIN)
    shortcut_frame.pack(pady=(0, 24))
    tk.Checkbutton(
        shortcut_frame,
        text="Create desktop shortcut after saving",
        variable=shortcut_var,
        fg=_TEXT_MUTED,
        bg=_BG_MAIN,
        selectcolor=_BG_DARK,
        activebackground=_BG_MAIN,
        activeforeground=_TEXT,
        font=("Segoe UI", 10),
    ).pack()

    response: Dict[str, Optional[AegisConfig]] = {"config": None}

    def save_and_close() -> None:
        operator = name_entry.get().strip() or _default_operator_name()
        portal = (portal_entry.get() or "").strip().rstrip("/")
        account = (account_entry.get() or "").strip()
        pwd = password_entry.get() or ""
        response["config"] = AegisConfig(
            operator_name=operator,
            create_desktop_shortcut=bool(shortcut_var.get()),
            portal_base=portal,
            account_name=account,
            password=pwd,
        )
        root.destroy()

    def cancel() -> None:
        if existing:
            response["config"] = existing
        root.destroy()

    actions = tk.Frame(root, bg=_BG_MAIN)
    actions.pack(pady=(0, 24))
    tk.Button(
        actions,
        text="Save",
        command=save_and_close,
        fg="#FFFFFF",
        bg=_ACCENT,
        activebackground=_ACCENT_HOVER,
        activeforeground="#FFFFFF",
        relief=tk.FLAT,
        padx=20,
        pady=8,
        font=("Segoe UI", 11, "bold"),
        cursor="hand2",
    ).pack(side=tk.LEFT, padx=(0, 8))

    tk.Button(
        actions,
        text="Cancel",
        command=cancel,
        fg=_TEXT,
        bg=_BG_SIDEBAR,
        activebackground=_BG_INPUT,
        activeforeground=_TEXT,
        relief=tk.FLAT,
        padx=20,
        pady=8,
        font=("Segoe UI", 11),
        cursor="hand2",
    ).pack(side=tk.LEFT)

    root.mainloop()
    return response["config"]


def _default_config(*, create_desktop_shortcut: bool = False) -> AegisConfig:
    return AegisConfig(
        operator_name=_default_operator_name(),
        create_desktop_shortcut=create_desktop_shortcut,
        portal_base="",
        account_name="",
        password="",
    )


def ensure_default_configuration(*, create_desktop_shortcut: bool = False) -> AegisConfig:
    config_path = _config_path()
    config = _load_config(config_path)
    if config is None:
        config = _default_config(create_desktop_shortcut=create_desktop_shortcut)
    elif create_desktop_shortcut and not config.create_desktop_shortcut:
        config = AegisConfig(
            operator_name=config.operator_name,
            create_desktop_shortcut=True,
            portal_base=config.portal_base,
            account_name=config.account_name,
            password=config.password,
        )
    _save_config(config_path, config)
    _ensure_desktop_shortcut(config)
    return config


def configure() -> AegisConfig:
    """Open the configuration menu and persist any changes."""
    config_path = _config_path()
    existing = _load_config(config_path)
    config = _configuration_window(existing)
    if config is None:
        config = existing or _default_config()
    _save_config(config_path, config)
    _ensure_desktop_shortcut(config)
    return config


def _portal_login(portal_base: str, account_name: str, password: str) -> Optional[str]:
    """Login to portal and return session token, or None on failure."""
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


def _portal_fetch_messages(portal_base: str, token: str) -> List[dict]:
    """Fetch messages from portal API. Returns list of message dicts."""
    if not portal_base or not token:
        return []
    url = f"{portal_base.rstrip('/')}/api/aegis/chat/messages"
    try:
        req = urllib.request.Request(
            url,
            headers={"X-Aegis-Token": token},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            messages = data.get("messages") or []
            return messages if isinstance(messages, list) else []
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError):
        return []


def _portal_send_message(portal_base: str, token: str, message: str) -> bool:
    """Send message to portal API. Returns True on success."""
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


def _greeting(name: str) -> str:
    hour = time.localtime().tm_hour
    if 5 <= hour < 12:
        time_block = "Morning"
    elif 12 <= hour < 17:
        time_block = "Afternoon"
    elif 17 <= hour < 22:
        time_block = "Evening"
    else:
        time_block = "Night"
    return f"Good {time_block}, {name}."


def build_interface(root: tk.Tk, config: AegisConfig) -> tk.Tk:
    """Create and configure the A.E.G.I.S. command console (3-panel layout)."""
    root.title("AEGIS Operator Console")
    root.configure(bg=_BG_MAIN)
    root.geometry("1200x750")
    root.minsize(900, 550)

    # App icon
    assets_dir = _resolve_assets_dir()
    icon_path = assets_dir / "aegis_icon.ico"
    if icon_path.exists():
        try:
            root.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    # ttk styles — military/sci-fi look
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Aegis.TButton",
        background=_ACCENT,
        foreground="white",
        padding=(12, 6),
        borderwidth=0,
        font=("Segoe UI", 10, "bold"),
    )
    style.map("Aegis.TButton", background=[("active", _ACCENT_HOVER)])
    style.configure(
        "AegisSecondary.TButton",
        background=_BG_INPUT,
        foreground=_TEXT,
        padding=(8, 4),
        borderwidth=0,
        font=("Segoe UI", 10),
    )
    style.map("AegisSecondary.TButton", background=[("active", _BG_SIDEBAR)])

    # 3-panel layout: Server | Chat | Operators
    main_container = tk.Frame(root, bg=_BG_MAIN)
    main_container.pack(fill=tk.BOTH, expand=True)

    # Left: Server panel
    sidebar = tk.Frame(main_container, bg=_BG_SIDEBAR, width=220)
    sidebar.pack(side=tk.LEFT, fill=tk.Y)
    sidebar.pack_propagate(False)

    server_btn = tk.Frame(sidebar, bg=_BG_INPUT, width=48, height=48, cursor="hand2")
    server_btn.place(relx=0.5, y=16, anchor="n")
    tk.Label(
        server_btn,
        text="A",
        fg=_ACCENT,
        bg=_BG_INPUT,
        font=("Segoe UI", 18, "bold"),
    ).place(relx=0.5, rely=0.5, anchor="center")

    tk.Label(
        sidebar,
        text="SERVERS",
        fg=_TEXT_MUTED,
        bg=_BG_SIDEBAR,
        font=("Segoe UI", 9, "bold"),
    ).pack(anchor="w", padx=12, pady=(80, 4))

    tk.Label(
        sidebar,
        text="# general",
        fg=_TEXT,
        bg=_BG_SIDEBAR,
        font=("Segoe UI", 11),
        cursor="hand2",
    ).pack(anchor="w", padx=12, pady=4)

    # Center: Chat / main feed (with background)
    chat_area = tk.Frame(main_container, bg=_BG_MAIN)
    chat_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # Background image (tactical grid) — placed first, lowered so content stays on top
    bg_path = assets_dir / "background.png"
    bg_label = None
    if bg_path.exists():
        try:
            bg_image = tk.PhotoImage(file=str(bg_path))
            bg_label = tk.Label(chat_area, image=bg_image, bg=_BG_MAIN)
            bg_label.place(relwidth=1, relheight=1)
            bg_label.image = bg_image  # Keep reference
        except (tk.TclError, OSError):
            pass

    # Chat header
    header = tk.Frame(chat_area, bg=_BG_MAIN, height=48)
    header.pack(fill=tk.X)
    header.pack_propagate(False)

    tk.Label(
        header,
        text="# general",
        fg=_TEXT,
        bg=_BG_MAIN,
        font=("Segoe UI", 14, "bold"),
    ).pack(side=tk.LEFT, padx=16, pady=12)

    status_dot = tk.Label(header, text="●", fg=_ONLINE, bg=_BG_MAIN, font=("Segoe UI", 10))
    status_dot.pack(side=tk.LEFT, padx=(0, 4))
    status_label = tk.Label(
        header,
        text="Local — messages stored securely",
        fg=_TEXT_MUTED,
        bg=_BG_MAIN,
        font=("Segoe UI", 11),
    )
    status_label.pack(side=tk.LEFT)

    settings_btn = ttk.Button(header, text="Settings", style="AegisSecondary.TButton")
    settings_btn.pack(side=tk.RIGHT, padx=8)

    # Message feed (styled)
    msg_frame = tk.Frame(chat_area, bg=_BG_MAIN)
    msg_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

    chat_feed = tk.Text(
        msg_frame,
        bg=_BG_MAIN,
        fg=_TEXT,
        insertbackground=_TEXT,
        borderwidth=0,
        font=("Segoe UI", 10),
        wrap=tk.WORD,
        relief=tk.FLAT,
        state=tk.DISABLED,
        padx=10,
        pady=10,
    )
    chat_feed.pack(fill=tk.BOTH, expand=True)
    chat_feed.tag_config("time", foreground=_TEXT_MUTED, font=("Segoe UI", 9))
    chat_feed.tag_config("user", foreground=_ACCENT, font=("Segoe UI", 10, "bold"))
    chat_feed.tag_config("msg", foreground=_TEXT, font=("Segoe UI", 10))
    chat_feed.tag_config("empty", foreground=_TEXT_MUTED, font=("Segoe UI", 10))

    if bg_label is not None:
        bg_label.lower()

    # Right: Operator list
    operator_panel = tk.Frame(main_container, bg=_BG_SIDEBAR, width=200)
    operator_panel.pack(side=tk.RIGHT, fill=tk.Y)
    operator_panel.pack_propagate(False)

    tk.Label(
        operator_panel,
        text="OPERATORS",
        fg=_TEXT_MUTED,
        bg=_BG_SIDEBAR,
        font=("Segoe UI", 9, "bold"),
    ).pack(anchor="w", padx=12, pady=(16, 4))

    # Placeholder operator (will show name_entry value)
    operator_list_frame = tk.Frame(operator_panel, bg=_BG_SIDEBAR)
    operator_list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

    # Bottom: Input bar
    input_bar = tk.Frame(root, bg=_BG_INPUT, height=60)
    input_bar.pack(fill=tk.X, side=tk.BOTTOM)
    input_bar.pack_propagate(False)

    input_inner = tk.Frame(input_bar, bg=_BG_INPUT)
    input_inner.pack(fill=tk.X, padx=16, pady=10)

    chat_input = tk.Entry(
        input_inner,
        fg=_TEXT,
        bg=_BG_MAIN,
        insertbackground=_TEXT,
        relief=tk.FLAT,
        font=("Segoe UI", 12),
    )
    chat_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, ipadx=12)
    chat_input.insert(0, "Message #general")

    def clear_placeholder(evt) -> None:
        if chat_input.get().strip() == "Message #general":
            chat_input.delete(0, tk.END)
            chat_input.configure(fg=_TEXT)

    def restore_placeholder(evt) -> None:
        if not chat_input.get().strip():
            chat_input.insert(0, "Message #general")
            chat_input.configure(fg=_TEXT_MUTED)

    chat_input.bind("<FocusIn>", clear_placeholder)
    chat_input.bind("<FocusOut>", restore_placeholder)
    chat_input.configure(fg=_TEXT_MUTED)

    send_btn = ttk.Button(input_inner, text="Send", style="Aegis.TButton")
    send_btn.pack(side=tk.RIGHT, padx=(12, 0))

    # Identity: display name (in operator panel)
    name_entry = tk.Entry(
        operator_list_frame,
        fg=_TEXT,
        bg=_BG_INPUT,
        insertbackground=_TEXT,
        relief=tk.FLAT,
        font=("Segoe UI", 10),
        width=14,
    )
    config_mutable = {
        "operator_name": config.operator_name,
        "portal_base": config.portal_base,
        "account_name": config.account_name,
        "password": config.password,
    }
    name_entry.insert(0, config.operator_name)
    name_entry.pack(anchor="w", pady=4, ipady=4, ipadx=8)

    tk.Label(
        operator_list_frame,
        text="(you)",
        fg=_TEXT_MUTED,
        bg=_BG_SIDEBAR,
        font=("Segoe UI", 9),
    ).pack(anchor="w", padx=(8, 0))

    def save_name_from_entry() -> None:
        name = name_entry.get().strip() or _default_operator_name()
        config_mutable["operator_name"] = name
        new_cfg = AegisConfig(
            operator_name=name,
            create_desktop_shortcut=config.create_desktop_shortcut,
            portal_base=config_mutable.get("portal_base", ""),
            account_name=config_mutable.get("account_name", ""),
            password=config_mutable.get("password", ""),
        )
        _save_config(_config_path(), new_cfg)

    name_entry.bind("<FocusOut>", lambda e: save_name_from_entry())
    name_entry.bind("<Return>", lambda e: save_name_from_entry())

    latest_count = {"value": 0}
    portal_token: Dict[str, Optional[str]] = {"token": None}

    def _get_portal_messages() -> list:
        base = config_mutable.get("portal_base") or ""
        account = config_mutable.get("account_name") or ""
        pwd = config_mutable.get("password") or ""
        if not base or not account or not pwd:
            return []
        token = portal_token.get("token")
        if not token:
            token = _portal_login(base, account, pwd)
            portal_token["token"] = token
        if token:
            return _portal_fetch_messages(base, token)
        return []

    def render_messages(messages: list) -> None:
        if not messages:
            chat_feed.configure(state=tk.NORMAL)
            chat_feed.delete("1.0", tk.END)
            chat_feed.insert(tk.END, "No messages yet. Say something!\n", "empty")
            chat_feed.configure(state=tk.DISABLED)
            return

        if len(messages) == latest_count["value"]:
            return
        latest_count["value"] = len(messages)

        chat_feed.configure(state=tk.NORMAL)
        chat_feed.delete("1.0", tk.END)
        for entry in messages:
            operator = entry.get("operator_handle") or entry.get("operator") or "Operator"
            message_text = entry.get("message") or ""
            created_at = entry.get("created_at") or ""
            try:
                ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
            except (ValueError, TypeError):
                ts = created_at
            chat_feed.insert(tk.END, f"[{ts}] ", "time")
            chat_feed.insert(tk.END, f"{operator}\n", "user")
            chat_feed.insert(tk.END, f"{message_text}\n\n", "msg")
        chat_feed.configure(state=tk.DISABLED)
        chat_feed.see(tk.END)

    def refresh_messages() -> None:
        portal_msgs = _get_portal_messages()
        if portal_msgs:
            status_label.config(text="Connected — synced with ALICE")
            render_messages(portal_msgs)
        else:
            status_label.config(text="Local — messages stored securely")
            render_messages(load_messages())
        root.after(_REFRESH_INTERVAL_MS, refresh_messages)

    def send_message() -> None:
        raw = chat_input.get().strip()
        if not raw or raw == "Message #general":
            return

        operator_name = name_entry.get().strip() or config_mutable.get("operator_name", "Operator")
        if not operator_name:
            return

        chat_input.delete(0, tk.END)
        chat_input.insert(0, "Message #general")
        chat_input.configure(fg=_TEXT_MUTED)

        config_mutable["operator_name"] = operator_name
        base = config_mutable.get("portal_base") or ""
        account = config_mutable.get("account_name") or ""
        pwd = config_mutable.get("password") or ""
        if base and account and pwd:
            token = portal_token.get("token") or _portal_login(base, account, pwd)
            portal_token["token"] = token
            if token and _portal_send_message(base, token, raw):
                messages = _portal_fetch_messages(base, token)
                render_messages(messages)
                return
        save_message(operator_name=operator_name, message=raw)
        messages = load_messages()
        render_messages(messages)

    send_btn.configure(command=send_message)
    chat_input.bind("<Return>", lambda e: send_message())

    def open_settings() -> None:
        current = AegisConfig(
            operator_name=config_mutable.get("operator_name", "Operator"),
            create_desktop_shortcut=config.create_desktop_shortcut,
            portal_base=config_mutable.get("portal_base", ""),
            account_name=config_mutable.get("account_name", ""),
            password=config_mutable.get("password", ""),
        )
        new_config = _configuration_window(current)
        if new_config:
            _save_config(_config_path(), new_config)
            _ensure_desktop_shortcut(new_config)
            name_entry.delete(0, tk.END)
            name_entry.insert(0, new_config.operator_name)
            config_mutable["operator_name"] = new_config.operator_name
            config_mutable["portal_base"] = new_config.portal_base
            config_mutable["account_name"] = new_config.account_name
            config_mutable["password"] = new_config.password
            portal_token["token"] = None

    settings_btn.configure(command=open_settings)

    # Initial load and refresh loop
    render_messages(load_messages())
    root.after(_REFRESH_INTERVAL_MS, refresh_messages)

    return root


def run() -> None:
    """Launch the A.E.G.I.S. operator console."""
    config = ensure_default_configuration()
    root = tk.Tk(className="A.E.G.I.S. Terminal")
    build_interface(root, config)
    root.mainloop()


if __name__ == "__main__":  # pragma: no cover - manual UI trigger
    run()
