from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nettrap.core.database import Database
from nettrap.gui import theme
from nettrap.utils.time_utils import local_date_range_to_utc_iso
from nettrap.utils.export import export_to_csv, export_to_json


class ExportView(QWidget):
    def __init__(self, db_path: str, config: dict, parent=None):
        super().__init__(parent)
        self.db = Database(db_path)
        self.config = config
        self.quick_buttons: dict[str, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        title = QLabel("EXPORT DATA")
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: 700;"
        )
        root.addWidget(title)

        root.addWidget(self._section_label("Filters"))
        filters = QVBoxLayout()
        filters.setSpacing(12)

        date_row = QHBoxLayout()
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        today = QDate.currentDate()
        self.start_date.setDate(today.addDays(-30))
        self.end_date.setDate(today)
        date_row.addWidget(QLabel("Date range:"))
        date_row.addWidget(self.start_date)
        date_row.addWidget(QLabel("->"))
        date_row.addWidget(self.end_date)
        for key, label in (("24h", "24h"), ("7d", "7d"), ("30d", "30d")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=key: self._apply_quick_range(value))
            self.quick_buttons[key] = button
            date_row.addWidget(button)
        date_row.addStretch(1)
        filters.addLayout(date_row)

        service_row = QHBoxLayout()
        service_row.addWidget(QLabel("Service:"))
        self.service_group = QButtonGroup(self)
        self.service_all = QRadioButton("All")
        self.service_ssh = QRadioButton("SSH only")
        self.service_http = QRadioButton("HTTP only")
        self.service_all.setChecked(True)
        for button in (self.service_all, self.service_ssh, self.service_http):
            self.service_group.addButton(button)
            service_row.addWidget(button)
        service_row.addStretch(1)
        filters.addLayout(service_row)

        include_row = QHBoxLayout()
        include_row.addWidget(QLabel("Include:"))
        self.include_sessions = QCheckBox("Sessions")
        self.include_events = QCheckBox("Events")
        self.include_alerts = QCheckBox("Alerts")
        self.include_sessions.setChecked(True)
        self.include_events.setChecked(True)
        self.include_alerts.setEnabled(False)
        include_row.addWidget(self.include_sessions)
        include_row.addWidget(self.include_events)
        include_row.addWidget(self.include_alerts)
        include_row.addStretch(1)
        filters.addLayout(include_row)
        root.addLayout(filters)

        root.addWidget(self._section_label("Format"))
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("Output:"))
        self.format_group = QButtonGroup(self)
        self.json_radio = QRadioButton("JSON")
        self.csv_radio = QRadioButton("CSV")
        if config["export"]["default_format"].lower() == "csv":
            self.csv_radio.setChecked(True)
        else:
            self.json_radio.setChecked(True)
        self.format_group.addButton(self.json_radio)
        self.format_group.addButton(self.csv_radio)
        format_row.addWidget(self.json_radio)
        format_row.addWidget(self.csv_radio)
        format_row.addStretch(1)
        root.addLayout(format_row)

        root.addWidget(self._section_label("Preview"))
        self.preview_label = QLabel("")
        self.preview_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 13px;"
        )
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 12px;"
        )
        self.export_button = QPushButton("Export to File")
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button.setStyleSheet(
            f"background: {theme.ACCENT_PRIMARY}; color: {theme.BACKGROUND_MAIN}; border: none; font-weight: 700; padding: 10px 16px;"
        )
        self.export_button.clicked.connect(self.export_now)
        root.addWidget(self.preview_label)
        root.addWidget(self.status_label)
        root.addWidget(self.export_button, 0)
        root.addStretch(1)

        for widget in (
            self.start_date,
            self.end_date,
            self.service_all,
            self.service_ssh,
            self.service_http,
            self.include_sessions,
            self.include_events,
            self.json_radio,
            self.csv_radio,
        ):
            signal = getattr(widget, "dateChanged", None)
            if signal is not None:
                signal.connect(self.refresh_preview)
            else:
                widget.toggled.connect(self.refresh_preview)

        self._apply_quick_range("30d")
        self.refresh_preview()

    def closeEvent(self, event):
        self.db.close()
        super().closeEvent(event)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 11px; font-weight: 700;"
        )
        return label

    def _apply_quick_range(self, key: str):
        today = QDate.currentDate()
        for button_key, button in self.quick_buttons.items():
            button.setChecked(button_key == key)
            if button_key == key:
                button.setStyleSheet(
                    f"background: {theme.ACCENT_PRIMARY}; color: {theme.BACKGROUND_MAIN}; border: none; font-weight: 700;"
                )
            else:
                button.setStyleSheet("")

        if key == "24h":
            self.start_date.setDate(today.addDays(-1))
        elif key == "7d":
            self.start_date.setDate(today.addDays(-7))
        elif key == "30d":
            self.start_date.setDate(today.addDays(-30))
        self.end_date.setDate(today)
        self.refresh_preview()

    def _service_filter(self) -> str | None:
        if self.service_ssh.isChecked():
            return "ssh"
        if self.service_http.isChecked():
            return "http"
        return None

    def _date_bounds(self) -> tuple[str, str]:
        start = self.start_date.date().toPyDate()
        end = self.end_date.date().toPyDate()
        return local_date_range_to_utc_iso(start, end)

    def refresh_preview(self):
        after, before = self._date_bounds()
        service = self._service_filter()
        sessions_count = self.db.get_total_sessions_count(service=service, after=after, before=before)
        events_count = self.db.get_total_events_count(service=service, after=after, before=before)

        self.preview_label.setText(
            f"Matching: {sessions_count:,} sessions | {events_count:,} events"
        )
        enabled = (self.include_sessions.isChecked() or self.include_events.isChecked()) and (
            sessions_count > 0 or events_count > 0
        )
        self.export_button.setEnabled(enabled)
        self.status_label.setText("" if enabled else "No data matches filters")

    def export_now(self):
        after, before = self._date_bounds()
        service = self._service_filter()
        sessions = self.db.export_sessions(service=service, after=after, before=before)
        events = self.db.export_events(service=service, after=after, before=before)

        if not self.include_sessions.isChecked():
            sessions = []
        if not self.include_events.isChecked():
            events = []

        default_dir = Path(self.config["export"]["default_directory"])
        default_dir.mkdir(parents=True, exist_ok=True)
        extension = "json" if self.json_radio.isChecked() else "csv"
        suggested = default_dir / f"nettrap_export.{extension}"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Data",
            str(suggested),
            f"{extension.upper()} Files (*.{extension});;All Files (*)",
        )
        if not path:
            return

        if self.json_radio.isChecked():
            export_to_json(sessions, events, path)
        else:
            export_to_csv(sessions, events, path)

        self.status_label.setText(f"Exported to {path}")
