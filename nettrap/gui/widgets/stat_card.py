from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from nettrap.gui import theme


class StatCard(QWidget):
    def __init__(self, icon: str, value: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setMinimumHeight(80)
        self.setMaximumHeight(80)
        self.setStyleSheet(
            f"""
            QWidget#statCard {{
                background: {theme.BACKGROUND_CARDS};
                border: 1px solid {theme.BORDER_DIVIDERS};
                border-radius: 8px;
            }}
            """
        )

        self._icon = QLabel(icon)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setFixedWidth(28)
        self._icon.setStyleSheet(f"color: {theme.ACCENT_PRIMARY}; font-size: 16px;")

        self._value = QLabel(value)
        self._value.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 28px; font-weight: 700;"
        )

        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)
        top_row.addWidget(self._icon)
        top_row.addWidget(self._value)
        top_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        layout.addLayout(top_row)
        layout.addWidget(self._label)

    def update_value(self, new_value: str):
        self._value.setText(new_value)
