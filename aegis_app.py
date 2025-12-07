"""Standalone UI launcher for the A.E.G.I.S. welcome screen.

Running this module opens a minimal terminal-style window that displays
an A.E.G.I.S. greeting. The design purposefully mirrors a classic
"hacker" terminal with green monospace text on a black background.

The window also exposes quick-access buttons that can open the chat and
A.L.I.C.E. experiences in the operator's default browser. URLs are
configurable via the ``AEGIS_CHAT_URL`` and ``AEGIS_ALICE_URL``
environment variables. If they are not provided, the launcher falls
back to sensible defaults under the ``AEGIS_PORTAL_URL`` base
(``http://localhost:8000``).
"""

from __future__ import annotations

import os
import tkinter as tk
import webbrowser
from tkinter import messagebox
from typing import Callable, Tuple

_TEXT_COLOR: str = "#00FF00"
_BACKGROUND_COLOR: str = "#000000"
_WINDOW_PADDING: Tuple[int, int] = (24, 24)
_MESSAGE: str = (
    "Welcome to A.E.G.I.S.\n"
    "The Administrative & Engagement Global Interface System stands ready"
)

_PORTAL_BASE = os.getenv("AEGIS_PORTAL_URL", "http://localhost:8000").strip() or "http://localhost:8000"
_PORTAL_BASE = _PORTAL_BASE.rstrip("/")
_CHAT_URL = os.getenv("AEGIS_CHAT_URL", f"{_PORTAL_BASE}/chat")
_ALICE_URL = os.getenv("AEGIS_ALICE_URL", f"{_PORTAL_BASE}/alice")


def _open_url(url: str, label: str) -> None:
    """Open the provided URL in the default browser with guard rails.

    Parameters
    ----------
    url:
        The URL to open.
    label:
        Human-friendly description for error and warning messages.
    """

    try:
        opened = webbrowser.open(url)
    except webbrowser.Error as exc:  # pragma: no cover - platform specific
        messagebox.showerror(
            "A.E.G.I.S. launcher", f"Could not open {label}: {exc}"  # pragma: no cover - platform specific
        )
        return

    if not opened:  # pragma: no cover - browser availability varies
        messagebox.showwarning(
            "A.E.G.I.S. launcher",
            f"No browser reported back when launching {label}.\n\n"
            f"Check that your system has a default browser configured and try again.",
        )


def _button_row(root: tk.Tk) -> tk.Frame:
    """Create a row of quick-launch buttons for chat and A.L.I.C.E."""

    frame = tk.Frame(root, bg=_BACKGROUND_COLOR)

    def add_button(text: str, command: Callable[[], None]) -> None:
        btn = tk.Button(
            frame,
            text=text,
            command=command,
            fg=_BACKGROUND_COLOR,
            bg=_TEXT_COLOR,
            activebackground=_TEXT_COLOR,
            activeforeground=_BACKGROUND_COLOR,
            relief=tk.FLAT,
            padx=12,
            pady=8,
            font=("Consolas", 12, "bold"),
            cursor="hand2",
        )
        btn.pack(side=tk.LEFT, padx=8)

    add_button("Open chat", lambda: _open_url(_CHAT_URL, "chat"))
    add_button("Open A.L.I.C.E.", lambda: _open_url(_ALICE_URL, "A.L.I.C.E."))

    return frame


def build_interface() -> tk.Tk:
    """Create and configure the A.E.G.I.S. terminal window.

    Returns
    -------
    tk.Tk
        The initialized Tk root window with content already added.
    """

    root = tk.Tk(className="A.E.G.I.S. Terminal")
    root.title("A.E.G.I.S. Terminal")
    root.configure(bg=_BACKGROUND_COLOR)

    # Use a monospace font to preserve the terminal aesthetic. The tuple form
    # avoids relying on platform-specific font strings.
    label = tk.Label(
        root,
        text=_MESSAGE,
        fg=_TEXT_COLOR,
        bg=_BACKGROUND_COLOR,
        font=("Consolas", 16, "bold"),
        justify=tk.CENTER,
    )
    label.pack(padx=_WINDOW_PADDING[0], pady=_WINDOW_PADDING[1])

    # Prevent the layout from shrinking too much if the user resizes the window.
    label.update_idletasks()
    min_width = label.winfo_width() + _WINDOW_PADDING[0] * 2
    min_height = label.winfo_height() + _WINDOW_PADDING[1] * 2
    root.minsize(min_width, min_height)

    buttons = _button_row(root)
    buttons.pack(pady=(16, _WINDOW_PADDING[1]))

    return root


def run() -> None:
    """Launch the A.E.G.I.S. terminal window and start the UI loop."""

    root = build_interface()
    root.mainloop()


if __name__ == "__main__":  # pragma: no cover - manual UI trigger
    run()
