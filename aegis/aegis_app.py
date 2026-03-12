"""Standalone UI launcher for the A.E.G.I.S. operator console.

Uses PySide6 (Qt) with modular layout:
  aegis_layout.py  — theme, geometry, panel structure
  aegis_chat.py    — message feed with styled tags, background image
  aegis_ui.py      — config dialog, main window, operator panel with status lights
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

try:
    from aegis.aegis_ui import AegisMainWindow, ensure_default_configuration
except ImportError:
    from aegis_ui import AegisMainWindow, ensure_default_configuration


def run() -> None:
    """Launch the A.E.G.I.S. operator console."""
    app = QApplication(sys.argv)
    app.setApplicationName("AEGIS")
    app.setStyle("Fusion")
    config = ensure_default_configuration()
    window = AegisMainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
