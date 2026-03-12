"""Layout constants and structure for the AEGIS operator console.

5-panel Discord-style layout:
  server_sidebar (70px) | channel_sidebar (220px) | chat_frame (expand) | operator_panel (220px)
  + input_bar (60px) at bottom
"""

from __future__ import annotations

# Military / sci-fi command console palette
BG_MAIN = "#0D1117"
BG_DARK = "#0A0D10"
BG_SIDEBAR = "#161B22"
BG_INPUT = "#21262D"
ACCENT = "#0096FF"
ACCENT_HOVER = "#58B4FF"
TEXT = "#E6EDF3"
TEXT_MUTED = "#8B949E"
ONLINE = "#3FB950"
OFFLINE = "#8B949E"

# Window geometry
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 760
WINDOW_MIN_WIDTH = 1000
WINDOW_MIN_HEIGHT = 650

# Panel widths
SERVER_SIDEBAR_WIDTH = 70
CHANNEL_SIDEBAR_WIDTH = 220
OPERATOR_PANEL_WIDTH = 220
INPUT_BAR_HEIGHT = 60

QSS = f"""
QMainWindow, QWidget {{
    background-color: {BG_MAIN};
}}
QFrame#serverSidebar {{
    background-color: {BG_DARK};
    border: none;
}}
QFrame#channelSidebar {{
    background-color: {BG_SIDEBAR};
    border: none;
}}
QFrame#operatorPanel {{
    background-color: {BG_SIDEBAR};
    border: none;
}}
QFrame#inputBar {{
    background-color: {BG_INPUT};
    border-top: 1px solid {BG_SIDEBAR};
}}
QLabel {{
    color: {TEXT};
}}
QLabel#muted {{
    color: {TEXT_MUTED};
}}
QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BG_SIDEBAR};
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 11px;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit::placeholder {{
    color: {TEXT_MUTED};
}}
QPushButton#primary {{
    background-color: {ACCENT};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 10px 20px;
    font-weight: bold;
}}
QPushButton#primary:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#secondary {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BG_SIDEBAR};
    border-radius: 4px;
    padding: 8px 16px;
}}
QPushButton#secondary:hover {{
    background-color: {BG_SIDEBAR};
}}
QTextEdit {{
    background-color: transparent;
    color: {TEXT};
    border: none;
    font-family: "Segoe UI", sans-serif;
    font-size: 10px;
    padding: 12px;
}}
QScrollBar:vertical {{
    background: {BG_SIDEBAR};
    width: 10px;
    border-radius: 5px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BG_INPUT};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""
