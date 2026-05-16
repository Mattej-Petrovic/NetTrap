from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nettrap.core.database import Database
from nettrap.gui import theme

_SEVERITY_COLORS = {
    "high": "#ef4444",
    "medium": "#f59e0b",
    "low": "#6b7280",
}

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class AlertsView(QWidget):
    def __init__(self, db_path: str, refresh_rate_ms: int, parent=None):
        super().__init__(parent)
        self.db = Database(db_path)
        self._active = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        header_row = QHBoxLayout()
        title = QLabel("ALERTS")
        title.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: 700;")
        header_row.addWidget(title)
        header_row.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        header_row.addWidget(self.count_label)
        root.addLayout(header_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Severity:"))
        self.filter_group = QButtonGroup(self)
        self._filter_buttons: dict[str, QRadioButton] = {}
        for key, label in (("all", "All"), ("high", "High"), ("medium", "Medium"), ("low", "Low")):
            btn = QRadioButton(label)
            if key == "all":
                btn.setChecked(True)
            btn.toggled.connect(self.refresh)
            self.filter_group.addButton(btn)
            self._filter_buttons[key] = btn
            filter_row.addWidget(btn)
        filter_row.addStretch(1)
        root.addLayout(filter_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Time", "Type", "Severity", "Source IP", "Message"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            f"background: {theme.BACKGROUND_MAIN}; color: {theme.TEXT_PRIMARY}; "
            f"alternate-background-color: {theme.BACKGROUND_SIDEBAR}; "
            f"gridline-color: {theme.BORDER_DIVIDERS};"
        )
        root.addWidget(self.table)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(refresh_rate_ms)
        self.refresh_timer.timeout.connect(self.refresh)

    def set_active(self, active: bool):
        self._active = active
        if active:
            self.refresh()
            self.refresh_timer.start()
        else:
            self.refresh_timer.stop()

    def refresh(self):
        severity = None
        for key, btn in self._filter_buttons.items():
            if key != "all" and btn.isChecked():
                severity = key
                break

        rows = self.db.get_alerts(limit=500, severity=severity)
        self.count_label.setText(f"{len(rows)} alert(s)")
        self.table.setRowCount(0)

        for alert in rows:
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)

            ts = str(alert.get("timestamp", ""))[:19].replace("T", " ")
            alert_type = alert.get("alert_type", "")
            sev = alert.get("severity", "low")
            source_ip = alert.get("source_ip") or alert.get("session_id", "")[:8]
            message = alert.get("message", "")

            ts_item = QTableWidgetItem(ts)
            type_item = QTableWidgetItem(alert_type.replace("_", " ").title())
            sev_item = QTableWidgetItem(sev.upper())
            ip_item = QTableWidgetItem(source_ip)
            msg_item = QTableWidgetItem(message)

            color = _SEVERITY_COLORS.get(sev, theme.TEXT_SECONDARY)
            sev_item.setForeground(Qt.GlobalColor.white)
            sev_item.setBackground(QColor(color))

            for item in (ts_item, type_item, sev_item, ip_item, msg_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.table.setItem(row_idx, 0, ts_item)
            self.table.setItem(row_idx, 1, type_item)
            self.table.setItem(row_idx, 2, sev_item)
            self.table.setItem(row_idx, 3, ip_item)
            self.table.setItem(row_idx, 4, msg_item)

    def closeEvent(self, event):
        self.refresh_timer.stop()
        self.db.close()
        super().closeEvent(event)
