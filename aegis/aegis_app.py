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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from typing import Dict, Optional, Tuple

try:
    from aegis.chat_store import load_messages, save_message
except ImportError:
    from chat_store import load_messages, save_message

# Discord-inspired palette
_BG_DARK: str = "#202225"       # Darkest (sidebar accent)
_BG_SIDEBAR: str = "#2F3136"    # Server/channel sidebar
_BG_MAIN: str = "#36393F"       # Main content area
_BG_INPUT: str = "#40444B"      # Input field
_ACCENT: str = "#5865F2"        # Discord blurple
_ACCENT_HOVER: str = "#4752C4"
_TEXT: str = "#DCDDDE"
_TEXT_MUTED: str = "#B9BBBE"
_ONLINE: str = "#43B581"
_WINDOW_PADDING: Tuple[int, int] = (0, 0)
_REFRESH_INTERVAL_MS = 2000     # Refresh messages from store
_MAX_MESSAGES = 500             # Prune older messages


@dataclass(frozen=True)
class AegisConfig:
    operator_name: str
    create_desktop_shortcut: bool


def _default_operator_name() -> str:
    return os.getenv("AEGIS_OPERATOR_NAME", os.getenv("USERNAME", "")).strip() or "Operator"


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
    )


def _save_config(path: Path, config: AegisConfig) -> None:
    payload = {
        "operator_name": config.operator_name,
        "create_desktop_shortcut": config.create_desktop_shortcut,
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

    if existing:
        operator_name = existing.operator_name
        create_shortcut = existing.create_desktop_shortcut

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
        text="Set your display name for the operator chat.",
        fg=_TEXT_MUTED,
        bg=_BG_MAIN,
        font=("Segoe UI", 10),
    )
    subtitle.pack(pady=(0, 20))

    form = tk.Frame(root, bg=_BG_MAIN)
    form.pack(padx=32, pady=(0, 16), fill=tk.BOTH)

    tk.Label(
        form,
        text="Display name",
        fg=_TEXT_MUTED,
        bg=_BG_MAIN,
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", pady=(0, 6))

    name_entry = tk.Entry(
        form,
        fg=_TEXT,
        bg=_BG_INPUT,
        insertbackground=_TEXT,
        relief=tk.FLAT,
        font=("Segoe UI", 12),
    )
    name_entry.insert(0, operator_name)
    name_entry.pack(fill=tk.X, ipady=8, ipadx=12, pady=(0, 20))

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
        response["config"] = AegisConfig(
            operator_name=operator,
            create_desktop_shortcut=bool(shortcut_var.get()),
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
    """Create and configure the A.E.G.I.S. Discord-style window."""
    root.title("A.E.G.I.S. — Operator Console")
    root.configure(bg=_BG_DARK)
    root.geometry("900x600")
    root.minsize(720, 480)

    # Main layout: sidebar + content
    main = tk.Frame(root, bg=_BG_DARK)
    main.pack(fill=tk.BOTH, expand=True)

    # Left sidebar (Discord server list style)
    sidebar = tk.Frame(main, bg=_BG_SIDEBAR, width=72)
    sidebar.pack(side=tk.LEFT, fill=tk.Y)
    sidebar.pack_propagate(False)

    # Server icon / logo
    server_btn = tk.Frame(sidebar, bg=_BG_MAIN, width=48, height=48, cursor="hand2")
    server_btn.place(relx=0.5, y=16, anchor="n")
    tk.Label(
        server_btn,
        text="A",
        fg=_TEXT,
        bg=_BG_MAIN,
        font=("Segoe UI", 18, "bold"),
    ).place(relx=0.5, rely=0.5, anchor="center")

    # Channel list area
    channels_frame = tk.Frame(sidebar, bg=_BG_SIDEBAR)
    channels_frame.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(80, 0))

    tk.Label(
        channels_frame,
        text="# general",
        fg=_TEXT,
        bg=_BG_SIDEBAR,
        font=("Segoe UI", 11),
        cursor="hand2",
    ).pack(anchor="w", pady=4)

    # Right: channel header + messages + input
    content = tk.Frame(main, bg=_BG_MAIN)
    content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=0)

    # Channel header bar
    header = tk.Frame(content, bg=_BG_MAIN, height=48)
    header.pack(fill=tk.X)
    header.pack_propagate(False)

    tk.Label(
        header,
        text="# general",
        fg=_TEXT,
        bg=_BG_MAIN,
        font=("Segoe UI", 16, "bold"),
    ).pack(side=tk.LEFT, padx=16, pady=12)

    status_dot = tk.Label(
        header,
        text="●",
        fg=_ONLINE,
        bg=_BG_MAIN,
        font=("Segoe UI", 10),
    )
    status_dot.pack(side=tk.LEFT, padx=(0, 4))
    tk.Label(
        header,
        text="Local — messages stored securely",
        fg=_TEXT_MUTED,
        bg=_BG_MAIN,
        font=("Segoe UI", 12),
    ).pack(side=tk.LEFT)

    settings_btn = tk.Button(
        header,
        text="Settings",
        fg=_TEXT_MUTED,
        bg=_BG_MAIN,
        activebackground=_BG_INPUT,
        activeforeground=_TEXT,
        relief=tk.FLAT,
        padx=12,
        pady=4,
        font=("Segoe UI", 11),
        cursor="hand2",
    )
    settings_btn.pack(side=tk.RIGHT, padx=8)

    # Message area
    msg_frame = tk.Frame(content, bg=_BG_MAIN)
    msg_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

    chat_feed = tk.Text(
        msg_frame,
        bg=_BG_MAIN,
        fg=_TEXT,
        font=("Segoe UI", 13),
        wrap=tk.WORD,
        relief=tk.FLAT,
        state=tk.DISABLED,
        padx=16,
        pady=16,
        insertbackground=_TEXT,
    )
    chat_feed.pack(fill=tk.BOTH, expand=True)
    chat_feed.tag_configure("timestamp", foreground=_TEXT_MUTED, font=("Segoe UI", 11))
    chat_feed.tag_configure("username", foreground=_ACCENT, font=("Segoe UI", 13, "bold"))
    chat_feed.tag_configure("message", foreground=_TEXT, font=("Segoe UI", 13))
    chat_feed.tag_configure("empty", foreground=_TEXT_MUTED, font=("Segoe UI", 12))

    # Input area (Discord-style)
    input_frame = tk.Frame(content, bg=_BG_MAIN, height=68)
    input_frame.pack(fill=tk.X, padx=16, pady=(0, 16))
    input_frame.pack_propagate(False)

    input_inner = tk.Frame(input_frame, bg=_BG_INPUT)
    input_inner.pack(fill=tk.X, ipady=4, ipadx=16)

    chat_input = tk.Entry(
        input_inner,
        fg=_TEXT,
        bg=_BG_INPUT,
        insertbackground=_TEXT,
        relief=tk.FLAT,
        font=("Segoe UI", 14),
    )
    chat_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10)
    chat_input.insert(0, f"Message #general")

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

    send_btn = tk.Button(
        input_inner,
        text="Send",
        fg="#FFFFFF",
        bg=_ACCENT,
        activebackground=_ACCENT_HOVER,
        activeforeground="#FFFFFF",
        relief=tk.FLAT,
        padx=20,
        pady=8,
        font=("Segoe UI", 11, "bold"),
        cursor="hand2",
    )
    send_btn.pack(side=tk.RIGHT, padx=(12, 0))

    # Identity: display name in header
    name_entry = tk.Entry(
        header,
        fg=_TEXT,
        bg=_BG_INPUT,
        insertbackground=_TEXT,
        relief=tk.FLAT,
        font=("Segoe UI", 10),
        width=14,
    )
    config_mutable = {"operator_name": config.operator_name}
    name_entry.insert(0, config.operator_name)
    name_entry.pack(side=tk.RIGHT, padx=8, ipady=4, ipadx=8)

    def save_name_from_entry() -> None:
        name = name_entry.get().strip() or _default_operator_name()
        config_mutable["operator_name"] = name
        new_cfg = AegisConfig(operator_name=name, create_desktop_shortcut=config.create_desktop_shortcut)
        _save_config(_config_path(), new_cfg)

    name_entry.bind("<FocusOut>", lambda e: save_name_from_entry())
    name_entry.bind("<Return>", lambda e: save_name_from_entry())

    latest_count = {"value": 0}

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
            chat_feed.insert(tk.END, f"[{ts}] ", "timestamp")
            chat_feed.insert(tk.END, f"{operator}\n", "username")
            chat_feed.insert(tk.END, f"{message_text}\n\n", "message")
        chat_feed.configure(state=tk.DISABLED)
        chat_feed.see(tk.END)

    def refresh_messages() -> None:
        messages = load_messages()
        render_messages(messages)
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

        save_message(operator_name=operator_name, message=raw)
        config_mutable["operator_name"] = operator_name
        messages = load_messages()
        render_messages(messages)

    send_btn.configure(command=send_message)
    chat_input.bind("<Return>", lambda e: send_message())

    def open_settings() -> None:
        new_config = _configuration_window(config)
        if new_config:
            _save_config(_config_path(), new_config)
            _ensure_desktop_shortcut(new_config)
            name_entry.delete(0, tk.END)
            name_entry.insert(0, new_config.operator_name)
            config_mutable["operator_name"] = new_config.operator_name

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
