"""Standalone UI launcher for the A.E.G.I.S. operator console.

Uses PySide6 (Qt) for a professional, modern interface.
Messages are stored locally—no server connection required.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Dict, Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

try:
    from aegis.aegis_core import (
        AegisConfig,
        config_path,
        default_operator_name,
        desktop_shortcut_exists,
        ensure_desktop_shortcut,
        load_config,
        load_messages,
        portal_fetch_messages,
        portal_login,
        portal_send_message,
        resolve_assets_dir,
        save_config,
        save_message,
    )
except ImportError:
    from aegis_core import (
        AegisConfig,
        config_path,
        default_operator_name,
        desktop_shortcut_exists,
        ensure_desktop_shortcut,
        load_config,
        load_messages,
        portal_fetch_messages,
        portal_login,
        portal_send_message,
        resolve_assets_dir,
        save_config,
        save_message,
    )

_REFRESH_INTERVAL_MS = 2000

# Military / sci-fi command console palette
BG_MAIN = "#0D1117"
BG_SIDEBAR = "#161B22"
BG_INPUT = "#21262D"
ACCENT = "#0096FF"
ACCENT_HOVER = "#58B4FF"
TEXT = "#E6EDF3"
TEXT_MUTED = "#8B949E"
ONLINE = "#3FB950"

QSS = f"""
QMainWindow, QWidget {{
    background-color: {BG_MAIN};
}}
QFrame#sidebar {{
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
    font-size: 12px;
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
QPlainTextEdit {{
    background-color: transparent;
    color: {TEXT};
    border: none;
    font-family: "Segoe UI", sans-serif;
    font-size: 11px;
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


def _default_config(*, create_desktop_shortcut: bool = False) -> AegisConfig:
    return AegisConfig(
        operator_name=default_operator_name(),
        create_desktop_shortcut=create_desktop_shortcut,
        portal_base="",
        account_name="",
        password="",
    )


def ensure_default_configuration(*, create_desktop_shortcut: bool = False) -> AegisConfig:
    path = config_path()
    config = load_config(path)
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
    save_config(path, config)
    ensure_desktop_shortcut(config)
    return config


class ConfigDialog(QDialog):
    """Configuration dialog for operator name and portal credentials."""

    def __init__(self, existing: Optional[AegisConfig], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("A.E.G.I.S. Configuration")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {BG_MAIN}; }}
            QLabel {{ color: {TEXT}; }}
            QLineEdit {{
                background-color: {BG_INPUT};
                color: {TEXT};
                border: 1px solid {BG_SIDEBAR};
                border-radius: 4px;
                padding: 8px;
            }}
            QCheckBox {{ color: {TEXT}; }}
            QPushButton#primary {{
                background-color: {ACCENT};
                color: white;
                border: none;
                padding: 10px 24px;
                font-weight: bold;
            }}
            QPushButton#secondary {{
                background-color: {BG_SIDEBAR};
                color: {TEXT};
                border: none;
                padding: 10px 24px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        title = QLabel("Configure A.E.G.I.S.")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel("Display name and portal credentials for mirrored ALICE chat.")
        subtitle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(12)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Operator")
        self.portal_edit = QLineEdit()
        self.portal_edit.setPlaceholderText("https://yoursite.com")
        self.account_edit = QLineEdit()
        self.account_edit.setPlaceholderText("Operator ID")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("••••••••")

        if existing:
            self.name_edit.setText(existing.operator_name)
            self.portal_edit.setText(existing.portal_base)
            self.account_edit.setText(existing.account_name)
            self.password_edit.setText(existing.password)
        else:
            self.name_edit.setText(default_operator_name())

        form.addRow("Display name", self.name_edit)
        form.addRow("Portal URL", self.portal_edit)
        form.addRow("Account name (operator ID)", self.account_edit)
        form.addRow("Password", self.password_edit)
        layout.addLayout(form)

        self.shortcut_cb = QCheckBox("Create desktop shortcut after saving")
        self.shortcut_cb.setChecked(not desktop_shortcut_exists())
        if existing:
            self.shortcut_cb.setChecked(existing.create_desktop_shortcut)
        layout.addWidget(self.shortcut_cb)

        buttons = QDialogButtonBox()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        buttons.addButton(save_btn, QDialogButtonBox.AcceptRole)
        buttons.addButton(cancel_btn, QDialogButtonBox.RejectRole)
        layout.addWidget(buttons)

    def get_config(self) -> AegisConfig:
        return AegisConfig(
            operator_name=self.name_edit.text().strip() or default_operator_name(),
            create_desktop_shortcut=self.shortcut_cb.isChecked(),
            portal_base=(self.portal_edit.text() or "").strip().rstrip("/"),
            account_name=(self.account_edit.text() or "").strip(),
            password=self.password_edit.text() or "",
        )


class AegisMainWindow(QMainWindow):
    """Main AEGIS operator console window."""

    def __init__(self, config: AegisConfig):
        super().__init__()
        self.setWindowTitle("AEGIS Operator Console")
        self.setMinimumSize(900, 550)
        self.resize(1200, 750)
        self.setStyleSheet(QSS)

        # App icon
        assets = resolve_assets_dir()
        icon_path = assets / "aegis_icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 3-panel layout
        splitter = QSplitter()
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {BG_SIDEBAR}; }}")

        # Left: Server panel
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)

        server_icon = QLabel("A")
        server_icon.setAlignment(0x0004 | 0x0080)
        server_icon.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {ACCENT}; background: {BG_INPUT}; padding: 12px; border-radius: 8px;")
        server_icon.setFixedSize(56, 56)
        sidebar_layout.addWidget(server_icon, alignment=0x0001)

        sidebar_layout.addSpacing(24)
        servers_label = QLabel("SERVERS")
        servers_label.setObjectName("muted")
        servers_label.setStyleSheet(f"font-size: 9px; font-weight: bold; color: {TEXT_MUTED};")
        sidebar_layout.addWidget(servers_label)
        channel_label = QLabel("# general")
        channel_label.setCursor(13)  # PointingHandCursor
        sidebar_layout.addWidget(channel_label)
        sidebar_layout.addStretch()
        splitter.addWidget(sidebar)

        # Center: Chat area
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet(f"background: {BG_MAIN}; border-bottom: 1px solid {BG_SIDEBAR};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        header_layout.addWidget(QLabel("# general"))
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {ONLINE};")
        header_layout.addWidget(self.status_dot)
        self.status_label = QLabel("Local — messages stored securely")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        header_layout.addWidget(self.status_label)
        header_layout.addStretch()

        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("secondary")
        settings_btn.clicked.connect(self._open_settings)
        header_layout.addWidget(settings_btn)
        chat_layout.addWidget(header)

        # Message feed
        self.chat_feed = QPlainTextEdit()
        self.chat_feed.setReadOnly(True)
        self.chat_feed.setPlaceholderText("No messages yet. Say something!")
        chat_layout.addWidget(self.chat_feed)
        splitter.addWidget(chat_widget)

        # Right: Operator panel
        operator_panel = QFrame()
        operator_panel.setObjectName("operatorPanel")
        operator_panel.setFixedWidth(200)
        op_layout = QVBoxLayout(operator_panel)
        op_layout.setContentsMargins(12, 16, 12, 16)

        op_label = QLabel("OPERATORS")
        op_label.setObjectName("muted")
        op_label.setStyleSheet(f"font-size: 9px; font-weight: bold;")
        op_layout.addWidget(op_label)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Operator")
        self.name_edit.setText(config.operator_name)
        self.name_edit.setMaximumWidth(160)
        self.name_edit.editingFinished.connect(self._save_name)
        op_layout.addWidget(self.name_edit)
        op_layout.addWidget(QLabel("(you)"))
        op_layout.addStretch()
        splitter.addWidget(operator_panel)

        # Set splitter sizes (left, center, right)
        splitter.setSizes([220, 780, 200])
        main_layout.addWidget(splitter)

        # Bottom: Input bar
        input_bar = QFrame()
        input_bar.setObjectName("inputBar")
        input_bar.setFixedHeight(60)
        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(16, 10, 16, 10)

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Message #general")
        self.chat_input.returnPressed.connect(self._send_message)
        input_layout.addWidget(self.chat_input)

        send_btn = QPushButton("Send")
        send_btn.setObjectName("primary")
        send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(send_btn)
        main_layout.addWidget(input_bar)

        # State
        self.config_mutable: Dict[str, str] = {
            "operator_name": config.operator_name,
            "portal_base": config.portal_base,
            "account_name": config.account_name,
            "password": config.password,
        }
        self.portal_token: Optional[str] = None
        self.latest_count = 0

        # Refresh timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_messages)
        self.refresh_timer.start(_REFRESH_INTERVAL_MS)

        self._render_messages(load_messages())

    def _save_name(self) -> None:
        name = self.name_edit.text().strip() or default_operator_name()
        self.config_mutable["operator_name"] = name
        path = config_path()
        current = load_config(path) or _default_config()
        new_cfg = AegisConfig(
            operator_name=name,
            create_desktop_shortcut=current.create_desktop_shortcut,
            portal_base=current.portal_base,
            account_name=current.account_name,
            password=current.password,
        )
        save_config(path, new_cfg)

    def _get_portal_messages(self) -> list:
        base = self.config_mutable.get("portal_base") or ""
        account = self.config_mutable.get("account_name") or ""
        pwd = self.config_mutable.get("password") or ""
        if not base or not account or not pwd:
            return []
        if not self.portal_token:
            self.portal_token = portal_login(base, account, pwd)
        if self.portal_token:
            return portal_fetch_messages(base, self.portal_token)
        return []

    def _render_messages(self, messages: list) -> None:
        self.chat_feed.clear()
        if not messages:
            self.chat_feed.setPlainText("No messages yet. Say something!")
            return
        parts = []
        for entry in messages:
            operator = entry.get("operator_handle") or entry.get("operator") or "Operator"
            msg_text = entry.get("message") or ""
            created_at = entry.get("created_at") or ""
            try:
                ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
            except (ValueError, TypeError):
                ts = created_at
            parts.append(f"[{ts}] {operator}\n{msg_text}\n")
        self.chat_feed.setPlainText("\n".join(parts))
        self.chat_feed.verticalScrollBar().setValue(self.chat_feed.verticalScrollBar().maximum())
        self.latest_count = len(messages)

    def _refresh_messages(self) -> None:
        portal_msgs = self._get_portal_messages()
        if portal_msgs:
            self.status_label.setText("Connected — synced with ALICE")
            self._render_messages(portal_msgs)
        else:
            self.status_label.setText("Local — messages stored securely")
            self._render_messages(load_messages())

    def _send_message(self) -> None:
        raw = self.chat_input.text().strip()
        if not raw or raw == "Message #general":
            return
        operator_name = self.name_edit.text().strip() or self.config_mutable.get("operator_name", "Operator")
        if not operator_name:
            return

        self.chat_input.clear()
        self.chat_input.setPlaceholderText("Message #general")
        self.config_mutable["operator_name"] = operator_name

        base = self.config_mutable.get("portal_base") or ""
        account = self.config_mutable.get("account_name") or ""
        pwd = self.config_mutable.get("password") or ""
        if base and account and pwd:
            if not self.portal_token:
                self.portal_token = portal_login(base, account, pwd)
            if self.portal_token and portal_send_message(base, self.portal_token, raw):
                self._render_messages(portal_fetch_messages(base, self.portal_token))
                return
        save_message(operator_name=operator_name, message=raw)
        self._render_messages(load_messages())

    def _open_settings(self) -> None:
        path = config_path()
        current = load_config(path) or _default_config()
        # Sync in-memory name (user may have edited in operator panel)
        name = self.name_edit.text().strip() or default_operator_name()
        current = AegisConfig(
            operator_name=name,
            create_desktop_shortcut=current.create_desktop_shortcut,
            portal_base=current.portal_base,
            account_name=current.account_name,
            password=current.password,
        )
        dlg = ConfigDialog(current, self)
        if dlg.exec() == QDialog.Accepted:
            new_config = dlg.get_config()
            save_config(config_path(), new_config)
            ensure_desktop_shortcut(new_config)
            self.name_edit.setText(new_config.operator_name)
            self.config_mutable["operator_name"] = new_config.operator_name
            self.config_mutable["portal_base"] = new_config.portal_base
            self.config_mutable["account_name"] = new_config.account_name
            self.config_mutable["password"] = new_config.password
            self.portal_token = None


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
