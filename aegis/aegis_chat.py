"""Chat area: message feed with styled rendering and background image."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

try:
    from aegis.aegis_layout import BG_MAIN, TEXT, TEXT_MUTED, ACCENT
except ImportError:
    from aegis_layout import BG_MAIN, TEXT, TEXT_MUTED, ACCENT


def _format_timestamp(timestamp: str) -> str:
    """Format ISO timestamp to HH:MM."""
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except (ValueError, TypeError):
        return timestamp


def render_message_html(entry: dict) -> str:
    """Render a single message as HTML with tags for timestamp, operator, message."""
    operator = entry.get("operator_handle") or entry.get("operator") or "Operator"
    msg_text = (entry.get("message") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ts = _format_timestamp(entry.get("created_at") or "")
    return f'<span style="color: {TEXT_MUTED}">[{ts}]</span> <span style="color: {ACCENT}; font-weight: bold;">{operator}</span>: <span style="color: {TEXT}">{msg_text}</span><br>'


class ChatWidget(QWidget):
    """Chat area with message feed, optional background image, and styled tags."""

    def __init__(self, assets_dir: Optional[Path] = None):
        super().__init__()
        self.setObjectName("chatFrame")
        self._assets_dir = assets_dir or Path(__file__).resolve().parent / "assets"
        self._latest_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Background image (tactical grid)
        self._bg_label = None
        bg_path = self._assets_dir / "background.png"
        if bg_path.exists():
            self._bg_label = QLabel(self)
            self._bg_label.setPixmap(QPixmap(str(bg_path)))
            self._bg_label.setScaledContents(True)
            self._bg_label.setStyleSheet(f"background: {BG_MAIN};")
            self._bg_label.lower()
            self._bg_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # Message feed (QTextEdit for rich HTML with timestamp/operator/message tags)
        self.chat_feed = QTextEdit()
        self.chat_feed.setReadOnly(True)
        self.chat_feed.setPlaceholderText("No messages yet. Say something!")
        self.chat_feed.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {TEXT};
                border: none;
                font-family: "Segoe UI", sans-serif;
                font-size: 10px;
                padding: 12px;
            }}
        """)
        layout.addWidget(self.chat_feed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._bg_label:
            self._bg_label.setGeometry(0, 0, self.width(), self.height())
            self._bg_label.lower()

    def render_messages(self, messages: list) -> None:
        """Render messages with timestamp, operator, message tags."""
        if not messages:
            self.chat_feed.setHtml("<p style='color: #8B949E'>No messages yet. Say something!</p>")
            self._latest_count = 0
            return

        if len(messages) == self._latest_count:
            return
        self._latest_count = len(messages)

        html = "".join(render_message_html(m) for m in messages)
        self.chat_feed.setHtml(html)
        self.chat_feed.verticalScrollBar().setValue(self.chat_feed.verticalScrollBar().maximum())
