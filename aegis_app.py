"""Standalone UI launcher for the A.E.G.I.S. welcome screen.

Running this module opens a minimal terminal-style window that displays
an A.E.G.I.S. greeting. The design purposefully mirrors a classic
"hacker" terminal with green monospace text on a black background.
"""

from __future__ import annotations

import tkinter as tk
from typing import Tuple

_TEXT_COLOR: str = "#00FF00"
_BACKGROUND_COLOR: str = "#000000"
_WINDOW_PADDING: Tuple[int, int] = (24, 24)
_MESSAGE: str = (
    "Welcome to A.E.G.I.S.\n"
    "The Administrative & Engagement Global Interface System stands ready"
)


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

    return root


def run() -> None:
    """Launch the A.E.G.I.S. terminal window and start the UI loop."""

    root = build_interface()
    root.mainloop()


if __name__ == "__main__":  # pragma: no cover - manual UI trigger
    run()
