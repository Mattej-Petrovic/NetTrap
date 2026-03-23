from __future__ import annotations

import json
from datetime import datetime, timedelta

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from nettrap.core.database import Database
from nettrap.gui import theme
from nettrap.gui.widgets.session_table import SessionTable
from nettrap.utils.time_utils import format_local_time, local_today_start_utc_iso

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc


class TimelineMarker(QWidget):
    def __init__(self, hollow: bool, show_top: bool, show_bottom: bool, parent=None):
        super().__init__(parent)
        self.hollow = hollow
        self.show_top = show_top
        self.show_bottom = show_bottom
        self.setFixedWidth(28)
        self.setMinimumHeight(48)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = 14
        y = 18
        painter.setPen(QPen(QColor(theme.ACCENT_PRIMARY), 2))
        if self.show_top:
            painter.drawLine(x, 0, x, y - 6)
        if self.show_bottom:
            painter.drawLine(x, y + 6, x, self.height())

        if self.hollow:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.ACCENT_PRIMARY), 2))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ACCENT_PRIMARY))
        painter.drawEllipse(x - 5, y - 5, 10, 10)


class TimelineEntry(QWidget):
    def __init__(
        self,
        timestamp: str,
        title: str,
        detail: str,
        hollow: bool,
        show_top: bool,
        show_bottom: bool,
        parent=None,
    ):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(TimelineMarker(hollow, show_top, show_bottom))

        text_block = QVBoxLayout()
        text_block.setContentsMargins(0, 0, 0, 8)
        text_block.setSpacing(2)

        ts = QLabel(timestamp)
        ts.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-family: '{theme.FONT_MONO}', '{theme.FONT_MONO_FALLBACK}'; font-size: 12px;"
        )
        headline = QLabel(title.upper())
        headline.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 13px; font-weight: 700;"
        )
        text_block.addWidget(ts)
        text_block.addWidget(headline)
        if detail:
            body = QLabel(detail)
            body.setWordWrap(True)
            body.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
            text_block.addWidget(body)

        root.addLayout(text_block, 1)


class SessionsView(QWidget):
    def __init__(self, db_path: str, refresh_rate_ms: int, event_queue=None, parent=None):
        super().__init__(parent)
        del event_queue
        self.db = Database(db_path)
        self._sessions_by_id: dict[str, dict] = {}
        self._current_session_id: str | None = None

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search IP, username, path")
        self.service_filter = QComboBox()
        self.service_filter.addItem("All", None)
        self.service_filter.addItem("SSH", "ssh")
        self.service_filter.addItem("HTTP", "http")
        self.date_filter = QComboBox()
        self.date_filter.addItem("Today", "today")
        self.date_filter.addItem("Last 7 days", "7d")
        self.date_filter.addItem("Last 30 days", "30d")
        self.date_filter.addItem("All", "all")

        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(QLabel("Search"))
        controls.addWidget(self.search_input, 1)
        controls.addWidget(self.service_filter)
        controls.addWidget(self.date_filter)

        self.table = SessionTable()
        self.table.session_selected.connect(self._show_session_detail)

        self.detail_panel = self._build_detail_panel()
        self.detail_panel.hide()

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([480, 320])
        self.splitter = splitter

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)
        root.addLayout(controls)
        self.empty_state = QLabel("No sessions found.")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 16px; font-weight: 600; padding: 12px 0;"
        )
        root.addWidget(self.empty_state)
        root.addWidget(splitter, 1)

        self.search_input.textChanged.connect(self.refresh)
        self.service_filter.currentIndexChanged.connect(self.refresh)
        self.date_filter.currentIndexChanged.connect(self.refresh)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(refresh_rate_ms)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()

        self.refresh()

    def closeEvent(self, event):
        self.refresh_timer.stop()
        self.db.close()
        super().closeEvent(event)

    def refresh(self):
        scroll_value = self.table.table.verticalScrollBar().value()
        selected_id = self._current_session_id or self.table.selected_session_id()
        sessions = self._query_sessions()
        self._sessions_by_id = {session["id"]: session for session in sessions}
        self.table.load_sessions(sessions)
        self.table.table.verticalScrollBar().setValue(scroll_value)
        self.empty_state.setVisible(len(sessions) == 0)
        self.splitter.setVisible(len(sessions) > 0)

        if selected_id and self.table.select_session(selected_id):
            self._current_session_id = selected_id
            self._update_detail(selected_id)
        elif selected_id:
            self._current_session_id = None
            self.detail_panel.hide()

    def _query_sessions(self) -> list[dict]:
        query = """
            SELECT
                s.*,
                COUNT(e.id) AS event_count
            FROM sessions AS s
            LEFT JOIN events AS e ON e.session_id = s.id
        """
        params: list = []
        conditions: list[str] = []

        service = self.service_filter.currentData()
        if service:
            conditions.append("s.service = ?")
            params.append(service)

        after = self._after_timestamp()
        if after:
            conditions.append("s.started_at >= ?")
            params.append(after)

        search = self.search_input.text().strip()
        if search:
            like = f"%{search}%"
            conditions.append(
                """
                (
                    s.source_ip LIKE ?
                    OR EXISTS (
                        SELECT 1
                        FROM events AS e2
                        WHERE e2.session_id = s.id
                        AND lower(e2.data) LIKE lower(?)
                    )
                )
                """
            )
            params.extend([like, like])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " GROUP BY s.id ORDER BY s.started_at DESC LIMIT 500"
        rows = self.db._fetch_rows(query, tuple(params))

        for row in rows:
            events = self.db.get_session_events(row["id"])
            row["search_blob"] = " ".join(
                json.dumps(event.get("data") or {}, ensure_ascii=False) for event in events
            )
        return rows

    def _after_timestamp(self) -> str | None:
        now = datetime.now(UTC)
        selection = self.date_filter.currentData()
        if selection == "today":
            return local_today_start_utc_iso(now)
        if selection == "7d":
            return (now - timedelta(days=7)).isoformat()
        if selection == "30d":
            return (now - timedelta(days=30)).isoformat()
        return None

    def _build_detail_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet(
            f"""
            QFrame {{
                background: {theme.BACKGROUND_CARDS};
                border: 1px solid {theme.BORDER_DIVIDERS};
                border-radius: 8px;
            }}
            """
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        self.detail_title = QLabel("SESSION DETAIL")
        self.detail_title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 13px; font-weight: 700;"
        )
        self.detail_summary = QLabel("")
        self.detail_summary.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")

        timeline_header = QLabel("TIMELINE")
        timeline_header.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 11px; font-weight: 700;"
        )

        self.timeline_area = QScrollArea()
        self.timeline_area.setWidgetResizable(True)
        self.timeline_area.setFrameShape(QFrame.Shape.NoFrame)
        self.timeline_container = QWidget()
        self.timeline_layout = QVBoxLayout(self.timeline_container)
        self.timeline_layout.setContentsMargins(0, 0, 0, 0)
        self.timeline_layout.setSpacing(0)
        self.timeline_layout.addStretch(1)
        self.timeline_area.setWidget(self.timeline_container)

        layout.addWidget(self.detail_title)
        layout.addWidget(self.detail_summary)
        layout.addSpacing(4)
        layout.addWidget(timeline_header)
        layout.addWidget(self.timeline_area, 1)
        return panel

    def _show_session_detail(self, session_id: str):
        self._current_session_id = session_id
        self._update_detail(session_id)

    def _update_detail(self, session_id: str):
        session = self._sessions_by_id.get(session_id)
        if not session:
            self.detail_panel.hide()
            return

        self.detail_panel.show()
        events = self.db.get_session_events(session_id)
        self.detail_title.setText(f"SESSION DETAIL: {session_id}")
        self.detail_summary.setText(
            "IP: {ip} | Country: {country} | Duration: {duration} | Evts: {count}".format(
                ip=session.get("source_ip", "-"),
                country=self._format_country_label(session),
                duration=self._format_duration(session.get("duration_sec")),
                count=len(events),
            )
        )

        while self.timeline_layout.count() > 1:
            item = self.timeline_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        entries = [
            {
                "timestamp": self._time_only(session.get("started_at")),
                "title": f"CONNECTED from {session.get('source_ip', '-')}",
                "detail": "",
                "hollow": True,
            }
        ]

        for event in events:
            data = event.get("data") or {}
            if event.get("event_type") == "auth_attempt":
                title = "AUTH ATTEMPT"
                detail = f"{data.get('username', '')} / {data.get('password', '')}       fail"
            elif event.get("event_type") == "http_request":
                title = "HTTP REQUEST"
                detail = f"{data.get('method', 'GET')} {data.get('path', '/')}"
            else:
                title = str(event.get("event_type", "event")).replace("_", " ").upper()
                detail = json.dumps(data, ensure_ascii=False)
            entries.append(
                {
                    "timestamp": self._time_only(event.get("timestamp")),
                    "title": title,
                    "detail": detail,
                    "hollow": False,
                }
            )

        if session.get("ended_at"):
            entries.append(
                {
                    "timestamp": self._time_only(session.get("ended_at")),
                    "title": "DISCONNECTED",
                    "detail": f"({len(events)} attempts, {self._format_duration(session.get('duration_sec'))})",
                    "hollow": True,
                }
            )

        for index, entry in enumerate(entries):
            self.timeline_layout.insertWidget(
                index,
                TimelineEntry(
                    timestamp=entry["timestamp"],
                    title=entry["title"],
                    detail=entry["detail"],
                    hollow=entry["hollow"],
                    show_top=index > 0,
                    show_bottom=index < len(entries) - 1,
                ),
            )

    @staticmethod
    def _time_only(timestamp: str | None) -> str:
        return format_local_time(timestamp, default=timestamp[-8:] if timestamp else "--:--:--")

    @staticmethod
    def _format_duration(duration: float | None) -> str:
        if duration is None:
            return "active"
        return f"{duration:.1f}s"

    @staticmethod
    def _format_country_label(session: dict) -> str:
        country_name = str(session.get("country") or "").strip()
        country_code = str(session.get("country_code") or "").strip().upper()
        if country_name and country_code:
            return f"{country_name} ({country_code})"
        if country_name:
            return country_name
        if country_code:
            return country_code
        return "--"
