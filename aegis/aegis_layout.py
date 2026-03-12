"""Layout constants and structure for the AEGIS operator console.

AEGIS Tactical Palette — command software, not Discord.
Layout: Command Header | Channels | Operations Feed | Operators | Command Input
"""

from __future__ import annotations

# AEGIS Tactical Palette
BG_DARK = "#0E1116"
BG_SIDEBAR = "#141922"
BG_MAIN = "#1B2230"
BG_PANEL = "#20293A"
BG_INPUT = "#1B2230"

ACCENT = "#00D1FF"
ACCENT_HOVER = "#00A9CC"

TEXT = "#E6EDF3"
TEXT_MUTED = "#8B949E"

ONLINE = "#2ECC71"
WARNING = "#F1C40F"
ALERT = "#E74C3C"
OFFLINE = TEXT_MUTED

# Window geometry
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 760
WINDOW_MIN_WIDTH = 1000
WINDOW_MIN_HEIGHT = 650

# Panel dimensions
HEADER_HEIGHT = 40
CHANNEL_PANEL_WIDTH = 220
OPERATOR_PANEL_WIDTH = 220
INPUT_BAR_HEIGHT = 60

QSS = f"""
QMainWindow, QWidget {{
    background-color: {BG_MAIN};
}}
QFrame#header {{
    background-color: {BG_DARK};
    border: none;
}}
QFrame#channelPanel {{
    background-color: {BG_SIDEBAR};
    border: none;
}}
QFrame#operatorPanel {{
    background-color: {BG_PANEL};
    border: none;
}}
QFrame#inputBar {{
    background-color: {BG_DARK};
    border-top: 1px solid {BG_SIDEBAR};
}}
QLabel {{
    color: {TEXT};
}}
QLabel#muted {{
    color: {TEXT_MUTED};
}}
QLineEdit {{
    background-color: {BG_MAIN};
    color: {TEXT};
    border: 1px solid {BG_SIDEBAR};
    border-radius: 2px;
    padding: 8px 12px;
    font-family: Consolas, monospace;
    font-size: 10px;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit::placeholder {{
    color: {TEXT_MUTED};
}}
QPushButton#primary {{
    background-color: {ACCENT};
    color: {BG_DARK};
    border: none;
    border-radius: 2px;
    padding: 10px 20px;
    font-weight: bold;
}}
QPushButton#primary:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#secondary {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BG_SIDEBAR};
    border-radius: 2px;
    padding: 8px 16px;
}}
QPushButton#secondary:hover {{
    background-color: {BG_SIDEBAR};
}}
QTextEdit {{
    background-color: transparent;
    color: {TEXT};
    border: none;
    font-family: Consolas, monospace;
    font-size: 10px;
    padding: 12px;
}}
QScrollBar:vertical {{
    background: {BG_SIDEBAR};
    width: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BG_PANEL};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""
