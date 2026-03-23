from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from nettrap.gui import theme
from nettrap.utils.time_utils import format_local_time


class SessionTable(QWidget):
    session_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions: list[dict] = []
        self._service_filter: str | None = None
        self._search_filter: str | None = None

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("sessionTable")
        self.table.setHorizontalHeaderLabels(
            ["SESSION ID", "SOURCE IP", "SERVICE", "COUNTRY", "TIME", "EVENTS"]
        )
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._emit_selection)
        self.table.cellClicked.connect(self._emit_clicked)
        self.table.setStyleSheet(
            f"""
            QTableWidget#sessionTable {{
                background-color: {theme.BACKGROUND_CARDS};
                alternate-background-color: {theme.BACKGROUND_MAIN};
                color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER_DIVIDERS};
                border-radius: 8px;
                selection-background-color: #1C2128;
                selection-color: {theme.TEXT_PRIMARY};
            }}
            QTableWidget#sessionTable::item {{
                padding: 8px;
            }}
            QTableWidget#sessionTable::item:selected {{
                background-color: #1C2128;
            }}
            """
        )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSortIndicatorShown(True)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStyleSheet(
            f"""
            QHeaderView::section {{
                background-color: {theme.BACKGROUND_SIDEBAR};
                color: {theme.TEXT_SECONDARY};
                border: none;
                border-bottom: 1px solid {theme.BORDER_DIVIDERS};
                padding: 8px;
                font-size: 11px;
                font-weight: 700;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

    def load_sessions(self, sessions: list):
        self._sessions = list(sessions or [])
        self._apply_filters()

    def set_filter(self, service=None, search=None):
        self._service_filter = service
        self._search_filter = (search or "").strip().lower() or None
        self._apply_filters()

    def selected_session_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select_session(self, session_id: str) -> bool:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == session_id:
                self.table.selectRow(row)
                return True
        return False

    def _apply_filters(self):
        sessions = self._sessions
        if self._service_filter:
            sessions = [row for row in sessions if row.get("service") == self._service_filter]
        if self._search_filter:
            needle = self._search_filter
            sessions = [
                row
                for row in sessions
                if needle in (row.get("source_ip") or "").lower()
                or needle in (row.get("search_blob") or "").lower()
            ]

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(sessions))
        for row_index, session in enumerate(sessions):
            session_id = str(session.get("id", ""))
            service = str(session.get("service", "")).lower()
            country_name = str(session.get("country") or "").strip()
            values = [
                session_id[:8],
                str(session.get("source_ip", "")),
                service.upper(),
                self._format_country_code(session.get("country_code")),
                self._format_time(session.get("started_at")),
                str(session.get("event_count", 0)),
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, session_id)
                if column == 3 and country_name:
                    item.setToolTip(country_name)
                if column == 2:
                    item.setForeground(
                        QColor(theme.ACCENT_SSH if service == "ssh" else theme.ACCENT_HTTP)
                    )
                elif column in {3, 4, 5}:
                    item.setForeground(QColor(theme.TEXT_SECONDARY))
                self.table.setItem(row_index, column, item)

        self.table.setSortingEnabled(True)

    def _emit_clicked(self, row: int, column: int):
        del column
        item = self.table.item(row, 0)
        if item is not None:
            session_id = item.data(Qt.ItemDataRole.UserRole)
            if session_id:
                self.session_selected.emit(str(session_id))

    def _emit_selection(self):
        session_id = self.selected_session_id()
        if session_id:
            self.session_selected.emit(session_id)

    @staticmethod
    def _format_time(timestamp: str | None) -> str:
        return format_local_time(timestamp)

    @staticmethod
    def _format_country_code(country_code: str | None) -> str:
        if not country_code:
            return "--"
        return str(country_code).strip().upper() or "--"
