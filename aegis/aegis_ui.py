"""UI components: config dialog, main window, operator panel with status lights."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
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
    from aegis.aegis_chat import ChatWidget
    from aegis.aegis_layout import (
        ACCENT,
        BG_DARK,
        BG_INPUT,
        BG_MAIN,
        BG_SIDEBAR,
        CHANNEL_SIDEBAR_WIDTH,
        INPUT_BAR_HEIGHT,
        OFFLINE,
        ONLINE,
        OPERATOR_PANEL_WIDTH,
        QSS,
        SERVER_SIDEBAR_WIDTH,
        TEXT,
        TEXT_MUTED,
        WINDOW_HEIGHT,
        WINDOW_MIN_HEIGHT,
        WINDOW_MIN_WIDTH,
        WINDOW_WIDTH,
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
    from aegis_chat import ChatWidget
    from aegis_layout import (
        ACCENT,
        BG_DARK,
        BG_INPUT,
        BG_MAIN,
        BG_SIDEBAR,
        CHANNEL_SIDEBAR_WIDTH,
        INPUT_BAR_HEIGHT,
        OFFLINE,
        ONLINE,
        OPERATOR_PANEL_WIDTH,
        QSS,
        SERVER_SIDEBAR_WIDTH,
        TEXT,
        TEXT_MUTED,
        WINDOW_HEIGHT,
        WINDOW_MIN_HEIGHT,
        WINDOW_MIN_WIDTH,
        WINDOW_WIDTH,
    )

_REFRESH_INTERVAL_MS = 2000


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


def add_operator_row(panel: QWidget, name: str, online: bool = True) -> QFrame:
    """Add an operator row with status light (ops console style)."""
    row = QFrame(panel)
    row.setObjectName("operatorRow")
    row.setStyleSheet(f"background: {BG_SIDEBAR}; border: none;")
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(6, 4, 6, 4)
    row_layout.setSpacing(6)

    # Status indicator (circle)
    indicator = QLabel()
    color = ONLINE if online else OFFLINE
    indicator.setStyleSheet(f"""
        background: {color};
        border-radius: 5px;
        min-width: 10px;
        max-width: 10px;
        min-height: 10px;
        max-height: 10px;
    """)
    indicator.setFixedSize(10, 10)
    row_layout.addWidget(indicator)

    label = QLabel(name)
    label.setStyleSheet(f"color: {TEXT};")
    row_layout.addWidget(label)
    row_layout.addStretch()
    return row


class AegisMainWindow(QMainWindow):
    """Main AEGIS operator console window — 5-panel layout (server | channel | chat | operators) + input bar."""

    def __init__(self, config: AegisConfig):
        super().__init__()
        self.setWindowTitle("AEGIS Operator Console")
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
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

        # 5-panel layout
        splitter = QSplitter()
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {BG_SIDEBAR}; }}")

        # Left 1: Server icons (70px)
        server_sidebar = QFrame()
        server_sidebar.setObjectName("serverSidebar")
        server_sidebar.setFixedWidth(SERVER_SIDEBAR_WIDTH)
        server_layout = QVBoxLayout(server_sidebar)
        server_layout.setContentsMargins(8, 16, 8, 16)

        server_icon = QLabel("A")
        server_icon.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        server_icon.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {ACCENT}; background: {BG_INPUT}; padding: 12px; border-radius: 8px;")
        server_icon.setFixedSize(48, 48)
        server_layout.addWidget(server_icon, alignment=Qt.AlignHCenter)
        server_layout.addStretch()
        splitter.addWidget(server_sidebar)

        # Left 2: Channel list (220px)
        channel_sidebar = QFrame()
        channel_sidebar.setObjectName("channelSidebar")
        channel_sidebar.setFixedWidth(CHANNEL_SIDEBAR_WIDTH)
        channel_layout = QVBoxLayout(channel_sidebar)
        channel_layout.setContentsMargins(12, 16, 12, 16)

        server_label = QLabel("SERVERS")
        server_label.setStyleSheet(f"font-size: 9px; font-weight: bold; color: {TEXT_MUTED};")
        channel_layout.addWidget(server_label)
        channel_label = QLabel("# general")
        channel_label.setCursor(Qt.PointingHandCursor)
        channel_layout.addWidget(channel_label)
        channel_layout.addStretch()
        splitter.addWidget(channel_sidebar)

        # Center: Chat area (with background, styled messages)
        chat_container = QWidget()
        chat_layout = QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)

        # Chat header
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

        self.chat_widget = ChatWidget(assets)
        chat_layout.addWidget(self.chat_widget)
        splitter.addWidget(chat_container)

        # Right: Operator panel (220px) with status lights
        operator_panel = QFrame()
        operator_panel.setObjectName("operatorPanel")
        operator_panel.setFixedWidth(OPERATOR_PANEL_WIDTH)
        op_layout = QVBoxLayout(operator_panel)
        op_layout.setContentsMargins(12, 16, 12, 16)

        op_label = QLabel("OPERATORS")
        op_label.setStyleSheet(f"font-size: 9px; font-weight: bold; color: {TEXT_MUTED};")
        op_layout.addWidget(op_label)

        self.operator_list = QWidget()
        self.operator_list_layout = QVBoxLayout(self.operator_list)
        self.operator_list_layout.setContentsMargins(0, 0, 0, 0)
        self.operator_list_layout.setSpacing(0)

        # Current user row with status light (ops console style)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Operator")
        self.name_edit.setText(config.operator_name)
        self.name_edit.setMaximumWidth(160)
        self.name_edit.editingFinished.connect(self._save_name)
        self.name_edit.setStyleSheet(f"background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BG_SIDEBAR}; padding: 6px 8px;")

        user_row = add_operator_row(self.operator_list, config.operator_name, online=True)
        self.operator_list_layout.addWidget(user_row)
        self.operator_list_layout.addWidget(self.name_edit)
        you_label = QLabel("(you)")
        you_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9px;")
        self.operator_list_layout.addWidget(you_label)
        self.operator_list_layout.addStretch()
        op_layout.addWidget(self.operator_list)
        splitter.addWidget(operator_panel)

        # Splitter sizes
        splitter.setSizes([SERVER_SIDEBAR_WIDTH, CHANNEL_SIDEBAR_WIDTH, 800, OPERATOR_PANEL_WIDTH])
        main_layout.addWidget(splitter)

        # Bottom: Input bar (60px)

        input_bar = QFrame()
        input_bar.setObjectName("inputBar")
        input_bar.setFixedHeight(INPUT_BAR_HEIGHT)
        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(10, 12, 10, 12)

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

        # Refresh timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_messages)
        self.refresh_timer.start(_REFRESH_INTERVAL_MS)

        self.chat_widget.render_messages(load_messages())

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

    def _refresh_messages(self) -> None:
        portal_msgs = self._get_portal_messages()
        if portal_msgs:
            self.status_label.setText("Connected — synced with ALICE")
            self.chat_widget.render_messages(portal_msgs)
        else:
            self.status_label.setText("Local — messages stored securely")
            self.chat_widget.render_messages(load_messages())

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
                self.chat_widget.render_messages(portal_fetch_messages(base, self.portal_token))
                return
        save_message(operator_name=operator_name, message=raw)
        self.chat_widget.render_messages(load_messages())

    def _open_settings(self) -> None:
        path = config_path()
        current = load_config(path) or _default_config()
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
