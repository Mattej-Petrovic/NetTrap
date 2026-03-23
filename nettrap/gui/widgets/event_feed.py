from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from nettrap.gui import theme
from nettrap.utils.time_utils import format_local_time


def service_lower(service: str) -> str:
    return (service or "").strip().lower()


class EventFeed(QWidget):
    def __init__(self, max_items=200, parent=None):
        super().__init__(parent)
        self.max_items = max_items
        self._items: list[QLabel] = []

        self.setObjectName("eventFeed")
        self.setStyleSheet(
            f"""
            QWidget#eventFeed {{
                background: {theme.BACKGROUND_CARDS};
                border: 1px solid {theme.BORDER_DIVIDERS};
                border-radius: 8px;
            }}
            """
        )

        title = QLabel("LIVE EVENT FEED")
        title.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 11px; font-weight: 700; letter-spacing: 1px;"
        )

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self._scroll.setWidget(self._container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self._scroll)

    def add_event(self, timestamp: str, service: str, summary: str):
        service_upper = service.upper()
        dot_color = theme.ACCENT_SSH if service_lower(service) == "ssh" else theme.ACCENT_HTTP
        display_time = format_local_time(timestamp, default=timestamp)

        line = QLabel()
        line.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-family: '{theme.FONT_MONO}', '{theme.FONT_MONO_FALLBACK}', monospace; font-size: 13px;"
        )
        line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        line.setTextFormat(Qt.TextFormat.RichText)
        line.setText(
            f"<span style='color:{theme.TEXT_SECONDARY};'>{display_time}</span>  "
            f"<span style='color:{dot_color};'>&#9679;</span>  "
            f"<span style='color:{theme.TEXT_PRIMARY}; font-weight:700;'>{service_upper}</span>  "
            f"<span style='color:{theme.TEXT_PRIMARY};'>{summary}</span>"
        )

        self._layout.insertWidget(0, line)
        self._items.insert(0, line)

        while len(self._items) > self.max_items:
            removed = self._items.pop()
            removed.setParent(None)
            removed.deleteLater()

        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().minimum())
