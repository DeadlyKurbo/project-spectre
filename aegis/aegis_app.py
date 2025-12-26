"""Standalone UI launcher for the A.E.G.I.S. welcome screen.

Running this module opens a minimal terminal-style window that displays
an A.E.G.I.S. greeting. The window also exposes quick-access buttons that
can open the chat and A.L.I.C.E. experiences in the operator's default
browser. URLs are configurable via the installer configuration window
or by setting the ``AEGIS_*`` environment variables.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Callable, Dict, Optional, Tuple

_TEXT_COLOR: str = "#00FF00"
_BACKGROUND_COLOR: str = "#000000"
_ACCENT_COLOR: str = "#34FF7F"
_MUTED_TEXT: str = "#9AFFC5"
_WINDOW_PADDING: Tuple[int, int] = (24, 24)

_DEFAULT_PORTAL_BASE = "http://localhost:8000"


@dataclass(frozen=True)
class AegisConfig:
    operator_name: str
    portal_base: str
    chat_url: str
    alice_url: str
    create_desktop_shortcut: bool


def _default_portal_base() -> str:
    base = os.getenv("AEGIS_PORTAL_URL", _DEFAULT_PORTAL_BASE).strip()
    return (base or _DEFAULT_PORTAL_BASE).rstrip("/")


def _default_chat_url(portal_base: str) -> str:
    return os.getenv("AEGIS_CHAT_URL", f"{portal_base}/chat").strip() or f"{portal_base}/chat"


def _default_alice_url(portal_base: str) -> str:
    return os.getenv("AEGIS_ALICE_URL", f"{portal_base}/alice").strip() or f"{portal_base}/alice"


def _default_operator_name() -> str:
    return os.getenv("AEGIS_OPERATOR_NAME", os.getenv("USERNAME", "")).strip() or "Operator"


def _config_path() -> Path:
    install_dir = Path(sys.argv[0]).resolve().parent
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
    chat_url = data.get("chat_url", _default_chat_url(portal_base)).strip() or _default_chat_url(portal_base)
    alice_url = data.get("alice_url", _default_alice_url(portal_base)).strip() or _default_alice_url(portal_base)

    return AegisConfig(
        operator_name=data.get("operator_name", _default_operator_name()).strip() or _default_operator_name(),
        portal_base=portal_base,
        chat_url=chat_url,
        alice_url=alice_url,
        create_desktop_shortcut=bool(data.get("create_desktop_shortcut", False)),
    )


def _save_config(path: Path, config: AegisConfig) -> None:
    payload = {
        "operator_name": config.operator_name,
        "portal_base": config.portal_base,
        "chat_url": config.chat_url,
        "alice_url": config.alice_url,
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


def _open_url(url: str, label: str) -> None:
    """Open the provided URL in the default browser with guard rails."""

    try:
        opened = webbrowser.open(url)
    except webbrowser.Error as exc:  # pragma: no cover - platform specific
        messagebox.showerror("A.E.G.I.S. launcher", f"Could not open {label}: {exc}")
        return

    if not opened:  # pragma: no cover - browser availability varies
        messagebox.showwarning(
            "A.E.G.I.S. launcher",
            f"No browser reported back when launching {label}.\n\n"
            "Check that your system has a default browser configured and try again.",
        )


def _button_row(root: tk.Tk, config: AegisConfig) -> tk.Frame:
    """Create a row of quick-launch buttons for chat and A.L.I.C.E."""

    frame = tk.Frame(root, bg=_BACKGROUND_COLOR)

    def add_button(text: str, command: Callable[[], None]) -> None:
        btn = tk.Button(
            frame,
            text=text,
            command=command,
            fg=_BACKGROUND_COLOR,
            bg=_TEXT_COLOR,
            activebackground=_ACCENT_COLOR,
            activeforeground=_BACKGROUND_COLOR,
            relief=tk.FLAT,
            padx=16,
            pady=8,
            font=("Consolas", 12, "bold"),
            cursor="hand2",
        )
        btn.pack(side=tk.LEFT, padx=8)

    add_button("Open chat", lambda: _open_url(config.chat_url, "chat"))
    add_button("Open A.L.I.C.E.", lambda: _open_url(config.alice_url, "A.L.I.C.E."))

    return frame


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

    install_dir = Path(sys.argv[0]).resolve().parent
    launcher = install_dir / "Launch-AEGIS.bat"
    target_path = launcher if launcher.exists() else Path(sys.executable)
    arguments = "" if launcher.exists() else str(Path(sys.argv[0]).resolve())
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


def _validate_urls(portal_base: str, chat_url: str, alice_url: str) -> Optional[str]:
    for label, value in (("Portal base", portal_base), ("Chat URL", chat_url), ("A.L.I.C.E. URL", alice_url)):
        if not (value.startswith("http://") or value.startswith("https://")):
            return f"{label} must start with http:// or https://"
    return None


def _configuration_window(existing: Optional[AegisConfig]) -> Optional[AegisConfig]:
    root = tk.Tk(className="A.E.G.I.S. Configuration")
    root.title("A.E.G.I.S. Configuration")
    root.configure(bg=_BACKGROUND_COLOR)

    portal_base = _default_portal_base()
    chat_url = _default_chat_url(portal_base)
    alice_url = _default_alice_url(portal_base)
    operator_name = _default_operator_name()
    create_shortcut = not _desktop_shortcut_exists()

    if existing:
        portal_base = existing.portal_base
        chat_url = existing.chat_url
        alice_url = existing.alice_url
        operator_name = existing.operator_name
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
        text="Update your operator details and portal endpoints before launching.",
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
    add_field("Portal base", portal_base)
    add_field("Chat URL", chat_url)
    add_field("A.L.I.C.E. URL", alice_url)

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
        normalized_chat = _normalize_url(fields["Chat URL"].get(), f"{normalized_portal}/chat")
        normalized_alice = _normalize_url(fields["A.L.I.C.E. URL"].get(), f"{normalized_portal}/alice")
        operator = fields["Operator name"].get().strip() or _default_operator_name()

        validation = _validate_urls(normalized_portal, normalized_chat, normalized_alice)
        if validation:
            messagebox.showerror("A.E.G.I.S. Configuration", validation)
            return

        response["config"] = AegisConfig(
            operator_name=operator,
            portal_base=normalized_portal,
            chat_url=normalized_chat,
            alice_url=normalized_alice,
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
            portal_base=_default_portal_base(),
            chat_url=_default_chat_url(_default_portal_base()),
            alice_url=_default_alice_url(_default_portal_base()),
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

    buttons = _button_row(root, config)
    buttons.pack(pady=(8, 12))

    status = _status_row(root, config)
    status.pack(fill=tk.X, padx=_WINDOW_PADDING[0], pady=(0, 12))

    controls = tk.Frame(root, bg=_BACKGROUND_COLOR)
    controls.pack(pady=(0, 16))

    def open_settings() -> None:
        new_config = _configuration_window(config)
        if new_config:
            _save_config(_config_path(), new_config)
            _ensure_desktop_shortcut(new_config)
            root.destroy()
            run()

    settings_button = tk.Button(
        controls,
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
    settings_button.pack()

    root.update_idletasks()
    min_width = max(message.winfo_width(), buttons.winfo_width()) + _WINDOW_PADDING[0] * 2
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
