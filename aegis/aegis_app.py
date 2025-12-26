"""Standalone UI launcher for the A.E.G.I.S. operator console.

Running this module opens a terminal-style window that displays
an A.E.G.I.S. greeting plus a built-in operator chat room. The chat
experience connects directly to the configured portal so operators can
participate without opening a browser.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from typing import Callable, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_TEXT_COLOR: str = "#00FF00"
_BACKGROUND_COLOR: str = "#000000"
_ACCENT_COLOR: str = "#34FF7F"
_MUTED_TEXT: str = "#9AFFC5"
_WINDOW_PADDING: Tuple[int, int] = (24, 24)
_CHAT_PANEL_BG = "#060606"
_CHAT_ENTRY_BG = "#101010"
_CHAT_STATUS_WARN = "#FFB86C"
_CHAT_STATUS_ERROR = "#FF6B6B"
_CHAT_POLL_INTERVAL_MS = 5000

_DEFAULT_PORTAL_BASE = "http://localhost:8000"


@dataclass(frozen=True)
class AegisConfig:
    operator_name: str
    operator_id_code: str
    portal_base: str
    create_desktop_shortcut: bool


def _default_portal_base() -> str:
    base = os.getenv("AEGIS_PORTAL_URL", _DEFAULT_PORTAL_BASE).strip()
    return (base or _DEFAULT_PORTAL_BASE).rstrip("/")


def _default_operator_name() -> str:
    return os.getenv("AEGIS_OPERATOR_NAME", os.getenv("USERNAME", "")).strip() or "Operator"


def _default_operator_id_code() -> str:
    return os.getenv("AEGIS_OPERATOR_ID", "").strip()


def _resolve_install_dir() -> Path:
    argv_path = Path(sys.argv[0])
    if argv_path.exists():
        if argv_path.is_dir():
            return argv_path.resolve()
        argv_parent = argv_path.resolve().parent
        if argv_parent.name == "dist" and (argv_parent.parent / "aegis_app.py").exists():
            return argv_parent.parent
        return argv_parent
    return Path(__file__).resolve().parent


def _resolve_launch_target(install_dir: Path) -> Path:
    dist_target = install_dir / "dist" / "aegis-welcome.pyz"
    if dist_target.exists():
        return dist_target
    argv_path = Path(sys.argv[0])
    if argv_path.exists():
        return argv_path.resolve()
    return Path(__file__).resolve()


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

    portal_base = data.get("portal_base", _default_portal_base()).strip() or _default_portal_base()
    portal_base = portal_base.rstrip("/")
    return AegisConfig(
        operator_name=data.get("operator_name", _default_operator_name()).strip() or _default_operator_name(),
        operator_id_code=data.get("operator_id_code", _default_operator_id_code()).strip(),
        portal_base=portal_base,
        create_desktop_shortcut=bool(data.get("create_desktop_shortcut", False)),
    )


def _save_config(path: Path, config: AegisConfig) -> None:
    payload = {
        "operator_name": config.operator_name,
        "operator_id_code": config.operator_id_code,
        "portal_base": config.portal_base,
        "create_desktop_shortcut": config.create_desktop_shortcut,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _normalize_url(value: str, fallback: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return fallback
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned.rstrip("/")
    scheme = "https" if fallback.startswith("https://") else "http"
    return f"{scheme}://{cleaned}".rstrip("/")


class ChatRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ChatSession:
    token: str
    operator_label: str
    moderator: bool
    expires_at: Optional[str]


@dataclass
class ChatClient:
    portal_base: str
    session: Optional[ChatSession] = None

    def _endpoint(self, path: str) -> str:
        base = self.portal_base.rstrip("/")
        return f"{base}{path}"

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> dict:
        url = self._endpoint(path)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request_headers = {"Accept": "application/json"}
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        req = Request(url, data=body, method=method, headers=request_headers)
        try:
            with urlopen(req, timeout=8) as response:
                raw = response.read().decode("utf-8")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ChatRequestError("Received an invalid response from the portal.") from exc
        except HTTPError as exc:
            detail = ""
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = payload.get("detail") or payload.get("message") or ""
            except (json.JSONDecodeError, OSError):
                detail = ""
            raise ChatRequestError(
                detail or f"Request failed with status {exc.code}.",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise ChatRequestError("Unable to reach the portal. Check your connection.") from exc

    def login(self, *, id_code: str, password: str, operator_name: str) -> ChatSession:
        payload = {
            "id_code": id_code,
            "password": password,
            "operator_name": operator_name,
        }
        response = self._request_json("/api/aegis/chat/login", method="POST", payload=payload)
        session = ChatSession(
            token=response.get("token", ""),
            operator_label=response.get("operator_label", operator_name),
            moderator=bool(response.get("moderator", False)),
            expires_at=response.get("expires_at"),
        )
        self.session = session
        return session

    def _auth_headers(self) -> dict:
        if not self.session:
            return {}
        return {"Authorization": f"Bearer {self.session.token}"}

    def fetch_messages(self) -> list[dict]:
        response = self._request_json(
            "/api/aegis/chat/messages", headers=self._auth_headers()
        )
        return response.get("messages", [])

    def send_message(self, message: str) -> dict:
        response = self._request_json(
            "/api/aegis/chat/messages",
            method="POST",
            payload={"message": message},
            headers=self._auth_headers(),
        )
        return response.get("message", {})


def _status_row(root: tk.Tk, config: AegisConfig) -> tk.Frame:
    frame = tk.Frame(root, bg=_BACKGROUND_COLOR)
    portal_label = tk.Label(
        frame,
        text=f"Portal: {config.portal_base}",
        fg=_MUTED_TEXT,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 10),
    )
    portal_label.pack(side=tk.LEFT)

    operator_label = tk.Label(
        frame,
        text=f"Operator ID: {config.operator_id_code or 'Unregistered'}",
        fg=_MUTED_TEXT,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 10),
    )
    operator_label.pack(side=tk.LEFT, padx=(18, 0))

    time_label = tk.Label(
        frame,
        text="",
        fg=_MUTED_TEXT,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 10),
    )
    time_label.pack(side=tk.RIGHT)

    def update_time() -> None:
        time_label.configure(text=time.strftime("%I:%M:%S %p").lstrip("0"))
        root.after(1000, update_time)

    update_time()
    return frame


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
        "$s.Description='Launch the A.E.G.I.S. welcome app';"
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
    launch_target = _resolve_launch_target(install_dir)
    arguments = _quote_windows_argument(str(launch_target))
    target_path = launcher
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / "A.E.G.I.S. Welcome.lnk"

    if shortcut_path.exists():
        return
    _create_windows_shortcut(shortcut_path, target_path, install_dir, arguments=arguments)


def _desktop_shortcut_exists() -> bool:
    if platform.system().lower() != "windows":
        return False
    shortcut_path = Path.home() / "Desktop" / "A.E.G.I.S. Welcome.lnk"
    return shortcut_path.exists()


def _validate_urls(portal_base: str) -> Optional[str]:
    for label, value in (("Portal base", portal_base),):
        if not (value.startswith("http://") or value.startswith("https://")):
            return f"{label} must start with http:// or https://"
    return None


def _configuration_window(existing: Optional[AegisConfig]) -> Optional[AegisConfig]:
    root = tk.Tk(className="A.E.G.I.S. Configuration")
    root.title("A.E.G.I.S. Configuration")
    root.configure(bg=_BACKGROUND_COLOR)

    portal_base = _default_portal_base()
    operator_name = _default_operator_name()
    operator_id_code = _default_operator_id_code()
    create_shortcut = not _desktop_shortcut_exists()

    if existing:
        portal_base = existing.portal_base
        operator_name = existing.operator_name
        operator_id_code = existing.operator_id_code
        create_shortcut = existing.create_desktop_shortcut

    header = tk.Label(
        root,
        text="Configure A.E.G.I.S.",
        fg=_ACCENT_COLOR,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 16, "bold"),
    )
    header.pack(pady=(16, 8))

    subtitle = tk.Label(
        root,
        text="Update your operator details and portal endpoint before launching.",
        fg=_MUTED_TEXT,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 10),
    )
    subtitle.pack(pady=(0, 16))

    form = tk.Frame(root, bg=_BACKGROUND_COLOR)
    form.pack(padx=20, pady=(0, 12), fill=tk.BOTH)

    fields: Dict[str, tk.Entry] = {}

    def add_field(label: str, value: str) -> None:
        row = tk.Frame(form, bg=_BACKGROUND_COLOR)
        row.pack(fill=tk.X, pady=6)
        lbl = tk.Label(
            row,
            text=label,
            fg=_MUTED_TEXT,
            bg=_BACKGROUND_COLOR,
            width=18,
            anchor="w",
            font=("Consolas", 10, "bold"),
        )
        lbl.pack(side=tk.LEFT)
        entry = tk.Entry(
            row,
            fg=_TEXT_COLOR,
            bg="#0C0C0C",
            insertbackground=_TEXT_COLOR,
            relief=tk.FLAT,
            font=("Consolas", 11),
        )
        entry.insert(0, value)
        entry.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        fields[label] = entry

    add_field("Operator name", operator_name)
    add_field("Operator ID code", operator_id_code)
    add_field("Portal base", portal_base)

    shortcut_var = tk.BooleanVar(value=create_shortcut)
    shortcut_frame = tk.Frame(root, bg=_BACKGROUND_COLOR)
    shortcut_frame.pack(pady=(4, 12))
    shortcut_checkbox = tk.Checkbutton(
        shortcut_frame,
        text="Create desktop shortcut after saving",
        variable=shortcut_var,
        fg=_MUTED_TEXT,
        bg=_BACKGROUND_COLOR,
        selectcolor=_BACKGROUND_COLOR,
        activebackground=_BACKGROUND_COLOR,
        activeforeground=_MUTED_TEXT,
        font=("Consolas", 10),
    )
    shortcut_checkbox.pack()

    response: Dict[str, Optional[AegisConfig]] = {"config": None}

    def save_and_close() -> None:
        raw_portal = fields["Portal base"].get()
        normalized_portal = _normalize_url(raw_portal, _default_portal_base())
        normalized_portal = normalized_portal.rstrip("/")
        operator = fields["Operator name"].get().strip() or _default_operator_name()
        operator_id = fields["Operator ID code"].get().strip()

        validation = _validate_urls(normalized_portal)
        if validation:
            messagebox.showerror("A.E.G.I.S. Configuration", validation)
            return

        response["config"] = AegisConfig(
            operator_name=operator,
            operator_id_code=operator_id,
            portal_base=normalized_portal,
            create_desktop_shortcut=bool(shortcut_var.get()),
        )
        root.destroy()

    def cancel() -> None:
        if existing:
            response["config"] = existing
        root.destroy()

    actions = tk.Frame(root, bg=_BACKGROUND_COLOR)
    actions.pack(pady=(4, 16))
    save_button = tk.Button(
        actions,
        text="Save configuration",
        command=save_and_close,
        fg=_BACKGROUND_COLOR,
        bg=_ACCENT_COLOR,
        activebackground=_TEXT_COLOR,
        activeforeground=_BACKGROUND_COLOR,
        relief=tk.FLAT,
        padx=16,
        pady=8,
        font=("Consolas", 11, "bold"),
    )
    save_button.pack(side=tk.LEFT, padx=8)

    cancel_button = tk.Button(
        actions,
        text="Cancel",
        command=cancel,
        fg=_MUTED_TEXT,
        bg="#1B1B1B",
        activebackground="#2A2A2A",
        activeforeground=_TEXT_COLOR,
        relief=tk.FLAT,
        padx=16,
        pady=8,
        font=("Consolas", 11, "bold"),
    )
    cancel_button.pack(side=tk.LEFT, padx=8)

    root.mainloop()
    return response["config"]


def _ensure_configuration() -> AegisConfig:
    config_path = _config_path()
    config = _load_config(config_path)
    if config is None:
        config = _configuration_window(config)
    if config is None:
        config = AegisConfig(
            operator_name=_default_operator_name(),
            operator_id_code=_default_operator_id_code(),
            portal_base=_default_portal_base(),
            create_desktop_shortcut=False,
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
        config = existing or AegisConfig(
            operator_name=_default_operator_name(),
            operator_id_code=_default_operator_id_code(),
            portal_base=_default_portal_base(),
            create_desktop_shortcut=False,
        )
    _save_config(config_path, config)
    _ensure_desktop_shortcut(config)
    return config


def build_interface(root: tk.Tk, config: AegisConfig) -> tk.Tk:
    """Create and configure the A.E.G.I.S. terminal window."""

    root.title("A.E.G.I.S. Terminal")
    root.configure(bg=_BACKGROUND_COLOR)

    greeting = tk.Label(
        root,
        text=_greeting(config.operator_name),
        fg=_ACCENT_COLOR,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 14, "bold"),
    )
    greeting.pack(padx=_WINDOW_PADDING[0], pady=(18, 6))

    message = tk.Label(
        root,
        text=(
            "Welcome to A.E.G.I.S.\n"
            "The Administrative & Engagement Global Interface System stands ready."
        ),
        fg=_TEXT_COLOR,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 14, "bold"),
        justify=tk.CENTER,
    )
    message.pack(padx=_WINDOW_PADDING[0], pady=(0, 12))

    status = _status_row(root, config)
    status.pack(fill=tk.X, padx=_WINDOW_PADDING[0], pady=(0, 12))

    console = tk.Frame(root, bg=_BACKGROUND_COLOR)
    console.pack(
        padx=_WINDOW_PADDING[0],
        pady=(4, 16),
        fill=tk.BOTH,
        expand=True,
    )

    left_panel = tk.Frame(console, bg=_BACKGROUND_COLOR)
    left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 18))

    right_panel = tk.Frame(console, bg=_CHAT_PANEL_BG)
    right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

    access_header = tk.Label(
        left_panel,
        text="Operator Access",
        fg=_ACCENT_COLOR,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 12, "bold"),
    )
    access_header.pack(anchor="w", pady=(0, 8))

    access_status = tk.Label(
        left_panel,
        text="Awaiting verification...",
        fg=_CHAT_STATUS_WARN,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 10, "bold"),
        justify=tk.LEFT,
    )
    access_status.pack(anchor="w", pady=(0, 12))

    login_frame = tk.Frame(left_panel, bg=_BACKGROUND_COLOR)
    login_frame.pack(fill=tk.X, pady=(0, 12))

    def login_field(label: str, value: str, *, mask: bool = False) -> tk.Entry:
        row = tk.Frame(login_frame, bg=_BACKGROUND_COLOR)
        row.pack(fill=tk.X, pady=4)
        tk.Label(
            row,
            text=label,
            fg=_MUTED_TEXT,
            bg=_BACKGROUND_COLOR,
            font=("Consolas", 10),
            width=16,
            anchor="w",
        ).pack(side=tk.LEFT)
        entry = tk.Entry(
            row,
            fg=_TEXT_COLOR,
            bg=_CHAT_ENTRY_BG,
            insertbackground=_TEXT_COLOR,
            relief=tk.FLAT,
            font=("Consolas", 10),
            show="•" if mask else "",
        )
        entry.insert(0, value)
        entry.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        return entry

    id_code_entry = login_field("ID code", config.operator_id_code)
    password_entry = login_field("Passphrase", "", mask=True)

    login_button = tk.Button(
        left_panel,
        text="Verify access",
        fg=_BACKGROUND_COLOR,
        bg=_ACCENT_COLOR,
        activebackground=_TEXT_COLOR,
        activeforeground=_BACKGROUND_COLOR,
        relief=tk.FLAT,
        padx=14,
        pady=6,
        font=("Consolas", 10, "bold"),
        cursor="hand2",
    )
    login_button.pack(anchor="w", pady=(0, 8))

    session_label = tk.Label(
        left_panel,
        text="Session: offline",
        fg=_MUTED_TEXT,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 9),
    )
    session_label.pack(anchor="w")

    chat_header = tk.Frame(right_panel, bg=_CHAT_PANEL_BG)
    chat_header.pack(fill=tk.X, padx=12, pady=(12, 4))

    tk.Label(
        chat_header,
        text="Operator Relay",
        fg=_ACCENT_COLOR,
        bg=_CHAT_PANEL_BG,
        font=("Consolas", 12, "bold"),
    ).pack(side=tk.LEFT)

    chat_status = tk.Label(
        chat_header,
        text="Relay offline",
        fg=_CHAT_STATUS_WARN,
        bg=_CHAT_PANEL_BG,
        font=("Consolas", 9, "bold"),
    )
    chat_status.pack(side=tk.RIGHT)

    chat_feed = tk.Text(
        right_panel,
        height=18,
        bg=_CHAT_PANEL_BG,
        fg=_TEXT_COLOR,
        font=("Consolas", 11),
        wrap=tk.WORD,
        relief=tk.FLAT,
        state=tk.DISABLED,
        padx=10,
        pady=10,
    )
    chat_feed.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
    chat_feed.tag_configure("meta", foreground=_MUTED_TEXT, font=("Consolas", 9, "bold"))
    chat_feed.tag_configure("message", foreground=_TEXT_COLOR, font=("Consolas", 11))
    chat_feed.tag_configure("operator", foreground=_ACCENT_COLOR, font=("Consolas", 10, "bold"))

    chat_controls = tk.Frame(right_panel, bg=_CHAT_PANEL_BG)
    chat_controls.pack(fill=tk.X, padx=12, pady=(0, 12))

    chat_input = tk.Entry(
        chat_controls,
        fg=_TEXT_COLOR,
        bg=_CHAT_ENTRY_BG,
        insertbackground=_TEXT_COLOR,
        relief=tk.FLAT,
        font=("Consolas", 11),
    )
    chat_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

    send_button = tk.Button(
        chat_controls,
        text="Send",
        fg=_BACKGROUND_COLOR,
        bg=_TEXT_COLOR,
        activebackground=_ACCENT_COLOR,
        activeforeground=_BACKGROUND_COLOR,
        relief=tk.FLAT,
        padx=14,
        pady=6,
        font=("Consolas", 10, "bold"),
        cursor="hand2",
    )
    send_button.pack(side=tk.RIGHT)

    client = ChatClient(config.portal_base)
    latest_message_id = {"value": None}
    poll_in_flight = {"value": False}
    polling_started = {"value": False}

    def set_access_status(text: str, *, is_error: bool = False) -> None:
        access_status.configure(
            text=text,
            fg=_CHAT_STATUS_ERROR if is_error else _ACCENT_COLOR,
        )

    def set_chat_status(text: str, *, is_error: bool = False) -> None:
        chat_status.configure(
            text=text,
            fg=_CHAT_STATUS_ERROR if is_error else _CHAT_STATUS_WARN,
        )

    def set_session_label(session: Optional[ChatSession]) -> None:
        if session and session.expires_at:
            session_label.configure(
                text=f"{session.operator_label} session expires at {session.expires_at}"
            )
        elif session:
            session_label.configure(text=f"{session.operator_label} session active")
        else:
            session_label.configure(text="Session: offline")

    def render_messages(messages: list[dict]) -> None:
        if not messages:
            chat_feed.configure(state=tk.NORMAL)
            chat_feed.delete("1.0", tk.END)
            chat_feed.insert(tk.END, "No relay traffic yet.\n", ("meta",))
            chat_feed.configure(state=tk.DISABLED)
            return

        newest_id = messages[-1].get("id")
        if newest_id == latest_message_id["value"]:
            return
        latest_message_id["value"] = newest_id

        chat_feed.configure(state=tk.NORMAL)
        chat_feed.delete("1.0", tk.END)
        for entry in messages:
            operator = entry.get("operator_handle") or entry.get("operator") or "Operator"
            message_text = entry.get("message") or ""
            created_at = entry.get("created_at") or ""
            timestamp = created_at
            try:
                timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
            except (ValueError, TypeError):
                timestamp = created_at
            chat_feed.insert(tk.END, f"[{timestamp}] ", ("meta",))
            chat_feed.insert(tk.END, f"{operator}\n", ("operator",))
            chat_feed.insert(tk.END, f"{message_text}\n\n", ("message",))
        chat_feed.configure(state=tk.DISABLED)
        chat_feed.see(tk.END)

    def run_async(action: Callable[[], dict | list], on_success: Callable, on_error: Callable[[Exception], None]) -> None:
        def worker() -> None:
            try:
                result = action()
            except Exception as exc:
                root.after(0, lambda: on_error(exc))
            else:
                root.after(0, lambda: on_success(result))

        threading.Thread(target=worker, daemon=True).start()

    def handle_login() -> None:
        id_code = id_code_entry.get().strip()
        password = password_entry.get()
        operator_name = config.operator_name

        if not id_code:
            set_access_status("Enter your operator ID code to continue.", is_error=True)
            return

        def do_login() -> dict:
            session = client.login(id_code=id_code, password=password, operator_name=operator_name)
            return {
                "session": session,
            }

        def login_success(data: dict) -> None:
            session = data.get("session")
            set_access_status("Access verified. Relay unlocked.", is_error=False)
            set_chat_status("Relay online", is_error=False)
            set_session_label(session)
            chat_input.configure(state=tk.NORMAL)
            send_button.configure(state=tk.NORMAL)
            id_code_entry.configure(state=tk.NORMAL)
            password_entry.delete(0, tk.END)
            if id_code != config.operator_id_code:
                config.operator_id_code = id_code
                _save_config(_config_path(), config)
            if not polling_started["value"]:
                polling_started["value"] = True
                schedule_poll()

        def login_error(exc: Exception) -> None:
            message = str(exc)
            if isinstance(exc, ChatRequestError) and exc.status_code == 403:
                message = "Access denied. You are not cleared for the relay."
            elif isinstance(exc, ChatRequestError) and exc.status_code == 423:
                message = "Operator access locked. Wait a few minutes and retry."
            set_access_status(message, is_error=True)
            set_chat_status("Relay offline", is_error=True)
            set_session_label(None)

        run_async(do_login, login_success, login_error)

    def poll_messages() -> None:
        if not client.session or poll_in_flight["value"]:
            return

        poll_in_flight["value"] = True

        def do_fetch() -> list[dict]:
            return client.fetch_messages()

        def fetch_success(messages: list[dict]) -> None:
            poll_in_flight["value"] = False
            render_messages(messages)
            set_chat_status("Relay online", is_error=False)

        def fetch_error(exc: Exception) -> None:
            poll_in_flight["value"] = False
            message = str(exc)
            if isinstance(exc, ChatRequestError) and exc.status_code in {401, 403}:
                client.session = None
                chat_input.configure(state=tk.DISABLED)
                send_button.configure(state=tk.DISABLED)
                set_access_status("Access check required.", is_error=True)
                set_session_label(None)
                message = "Relay access expired. Verify again."
            set_chat_status(message, is_error=True)

        run_async(do_fetch, fetch_success, fetch_error)

    def schedule_poll() -> None:
        poll_messages()
        root.after(_CHAT_POLL_INTERVAL_MS, schedule_poll)

    def send_message() -> None:
        message_text = chat_input.get().strip()
        if not message_text:
            return

        chat_input.delete(0, tk.END)

        def do_send() -> dict:
            return client.send_message(message_text)

        def send_success(_: dict) -> None:
            poll_messages()

        def send_error(exc: Exception) -> None:
            message = str(exc)
            if isinstance(exc, ChatRequestError) and exc.status_code in {401, 403}:
                client.session = None
                chat_input.configure(state=tk.DISABLED)
                send_button.configure(state=tk.DISABLED)
                set_access_status("Access check required.", is_error=True)
                set_session_label(None)
                message = "Relay access expired. Verify again."
            set_chat_status(message, is_error=True)

        run_async(do_send, send_success, send_error)

    login_button.configure(command=handle_login)
    send_button.configure(command=send_message, state=tk.DISABLED)
    chat_input.configure(state=tk.DISABLED)
    chat_input.bind("<Return>", lambda _: send_message())

    def open_settings() -> None:
        new_config = _configuration_window(config)
        if new_config:
            _save_config(_config_path(), new_config)
            _ensure_desktop_shortcut(new_config)
            root.destroy()
            run()

    settings_button = tk.Button(
        left_panel,
        text="Settings",
        command=open_settings,
        fg=_MUTED_TEXT,
        bg="#1B1B1B",
        activebackground="#2A2A2A",
        activeforeground=_TEXT_COLOR,
        relief=tk.FLAT,
        padx=12,
        pady=6,
        font=("Consolas", 10, "bold"),
        cursor="hand2",
    )
    settings_button.pack(anchor="w", pady=(12, 0))

    root.update_idletasks()
    min_width = max(message.winfo_width(), console.winfo_width()) + _WINDOW_PADDING[0] * 2
    min_height = root.winfo_height()
    root.minsize(min_width, min_height)

    return root


def run() -> None:
    """Launch the A.E.G.I.S. terminal window and start the UI loop."""

    config = _ensure_configuration()
    root = tk.Tk(className="A.E.G.I.S. Terminal")
    build_interface(root, config)
    root.mainloop()


if __name__ == "__main__":  # pragma: no cover - manual UI trigger
    run()
