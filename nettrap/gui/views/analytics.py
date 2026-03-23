from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from PyQt6.QtCore import QTimer, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from nettrap.core.database import Database
from nettrap.gui import theme
from nettrap.utils.time_utils import format_local_hour, to_local_datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc


class ChartPanel(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.setMinimumHeight(240)

    def _paint_panel(self, painter: QPainter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 8, 8)
        painter.fillPath(path, QColor(theme.BACKGROUND_CARDS))
        painter.setPen(QPen(QColor(theme.BORDER_DIVIDERS), 1))
        painter.drawPath(path)

        header_font = QFont(theme.FONT_SANS, 11)
        header_font.setBold(True)
        painter.setFont(header_font)
        painter.setPen(QColor(theme.TEXT_SECONDARY))
        painter.drawText(16, 28, self.title.upper())


class ConnectionsLineChart(ChartPanel):
    def __init__(self, parent=None):
        super().__init__("Connections Over Time", parent)
        self.points: list[tuple[str, int]] = []

    def set_points(self, points: list[tuple[str, int]]):
        self.points = points
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        self._paint_panel(painter)
        if not self.points:
            return

        chart_rect = self.rect().adjusted(52, 46, -18, -36)
        max_value = max(count for _, count in self.points) or 1
        step_x = chart_rect.width() / max(1, len(self.points) - 1)

        painter.setPen(QPen(QColor(theme.BORDER_DIVIDERS), 1))
        for index in range(4):
            y = chart_rect.bottom() - (index / 3) * chart_rect.height()
            painter.drawLine(chart_rect.left(), int(y), chart_rect.right(), int(y))

        painter.setPen(QColor(theme.TEXT_SECONDARY))
        painter.setFont(QFont(theme.FONT_SANS, 10))
        painter.drawText(18, chart_rect.top() + 4, str(max_value))
        painter.drawText(24, chart_rect.bottom() + 4, "0")

        points = []
        for index, (label, count) in enumerate(self.points):
            x = chart_rect.left() + index * step_x
            y = chart_rect.bottom() - (count / max_value) * chart_rect.height()
            points.append((x, y, label))

        painter.setPen(QPen(QColor(theme.ACCENT_PRIMARY), 2))
        for index in range(len(points) - 1):
            painter.drawLine(
                int(points[index][0]),
                int(points[index][1]),
                int(points[index + 1][0]),
                int(points[index + 1][1]),
            )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.ACCENT_PRIMARY))
        for x, y, _ in points:
            painter.drawEllipse(QRectF(x - 3, y - 3, 6, 6))

        painter.setPen(QColor(theme.TEXT_SECONDARY))
        painter.setFont(QFont(theme.FONT_SANS, 10))
        for x, _, label in points[:: max(1, len(points) // 4)]:
            painter.drawText(int(x) - 18, chart_rect.bottom() + 18, label)


class HorizontalBarsPanel(ChartPanel):
    def __init__(self, title: str, accent_color: str = theme.ACCENT_PRIMARY, parent=None):
        super().__init__(title, parent)
        self.accent_color = accent_color
        self.items: list[tuple[str, int]] = []

    def set_items(self, items: list[tuple[str, int]]):
        self.items = items[:10]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        self._paint_panel(painter)
        if not self.items:
            return

        max_value = max(value for _, value in self.items) or 1
        top = 52
        row_height = max(20, (self.height() - top - 16) // max(1, len(self.items)))
        painter.setFont(QFont(theme.FONT_MONO, 10))

        for index, (label, value) in enumerate(self.items):
            y = top + index * row_height
            bar_left = max(140, int(self.width() * 0.38))
            bar_width = max(30, self.width() - bar_left - 48)

            painter.setPen(QColor(theme.TEXT_PRIMARY))
            painter.drawText(16, y + 11, label[:30])
            painter.setPen(QPen(QColor(theme.BORDER_DIVIDERS), 1))
            painter.setBrush(QColor("#11161d"))
            painter.drawRoundedRect(QRectF(bar_left, y, bar_width, 12), 6, 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.accent_color))
            painter.drawRoundedRect(
                QRectF(bar_left, y, max(10, int(bar_width * (value / max_value))), 12),
                6,
                6,
            )
            painter.setPen(QColor(theme.TEXT_PRIMARY))
            painter.drawText(bar_left + bar_width + 8, y + 11, str(value))


class ServiceDistributionPanel(ChartPanel):
    def __init__(self, parent=None):
        super().__init__("Service Distribution", parent)
        self.items: list[tuple[str, int]] = []

    def set_items(self, items: list[tuple[str, int]]):
        self.items = items
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        self._paint_panel(painter)
        if not self.items:
            return

        total = sum(value for _, value in self.items) or 1
        top = 62
        row_gap = 56
        for index, (service, value) in enumerate(self.items[:2]):
            y = top + index * row_gap
            percent = int(round((value / total) * 100))
            bar_left = 84
            bar_width = max(60, self.width() - bar_left - 76)
            fill_width = max(10, int(bar_width * (value / total)))

            painter.setPen(QColor(theme.TEXT_PRIMARY))
            painter.drawText(16, y + 11, service.upper())
            painter.setPen(QPen(QColor(theme.BORDER_DIVIDERS), 1))
            painter.setBrush(QColor("#11161d"))
            painter.drawRoundedRect(QRectF(bar_left, y, bar_width, 14), 7, 7)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                QColor(theme.ACCENT_SSH if service == "ssh" else theme.ACCENT_HTTP)
            )
            painter.drawRoundedRect(QRectF(bar_left, y, fill_width, 14), 7, 7)
            painter.setPen(QColor(theme.TEXT_PRIMARY))
            painter.drawText(bar_left + bar_width + 8, y + 11, f"{percent}%")
            painter.setPen(QColor(theme.TEXT_SECONDARY))
            painter.drawText(bar_left + bar_width + 8, y + 27, str(value))


class AnalyticsView(QWidget):
    def __init__(self, db_path: str, refresh_rate_ms: int, parent=None):
        super().__init__(parent)
        self.db = Database(db_path)
        self.current_range = "24h"
        self.range_buttons: dict[str, QPushButton] = {}

        self.line_chart = ConnectionsLineChart()
        self.service_chart = ServiceDistributionPanel()
        self.ip_chart = HorizontalBarsPanel("Top Attacking IPs")
        self.credential_chart = HorizontalBarsPanel("Top Credentials")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)
        root.addLayout(self._build_range_selector())
        self.empty_state = QLabel("Not enough data. Run the honeypot to collect data.")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 16px; font-weight: 600; padding: 8px 0;"
        )
        root.addWidget(self.empty_state)

        self.chart_widget = QWidget()
        grid = QGridLayout(self.chart_widget)
        grid.setSpacing(12)
        grid.addWidget(self.line_chart, 0, 0)
        grid.addWidget(self.service_chart, 0, 1)
        grid.addWidget(self.ip_chart, 1, 0)
        grid.addWidget(self.credential_chart, 1, 1)
        root.addWidget(self.chart_widget, 1)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(refresh_rate_ms)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()
        self._update_range_styles()
        self.refresh()

    def closeEvent(self, event):
        self.refresh_timer.stop()
        self.db.close()
        super().closeEvent(event)

    def _build_range_selector(self):
        layout = QHBoxLayout()
        layout.setSpacing(8)
        for key, label in (("24h", "24h"), ("7d", "7d"), ("30d", "30d"), ("all", "All")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=key: self._set_range(value))
            self.range_buttons[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return layout

    def _set_range(self, value: str):
        self.current_range = value
        self._update_range_styles()
        self.refresh()

    def _update_range_styles(self):
        for key, button in self.range_buttons.items():
            if key == self.current_range:
                button.setStyleSheet(
                    f"background: {theme.ACCENT_PRIMARY}; color: {theme.BACKGROUND_MAIN}; border: none; font-weight: 700;"
                )
            else:
                button.setStyleSheet(
                    f"background: transparent; color: {theme.TEXT_PRIMARY}; border: 1px solid {theme.BORDER_DIVIDERS};"
                )

    def refresh(self):
        after = self._after_timestamp()
        sessions = self.db.export_sessions(after=after)
        events = self.db.export_events(after=after)

        self.line_chart.set_points(self._build_connection_points(sessions))
        self.service_chart.set_items(self._build_service_distribution(sessions))
        self.ip_chart.set_items(self._build_top_ips(sessions))
        self.credential_chart.set_items(self._build_top_credentials(events))
        has_data = bool(sessions and events)
        self.empty_state.setVisible(not has_data)
        self.chart_widget.setVisible(has_data)

    def _after_timestamp(self) -> str | None:
        now = datetime.now(UTC)
        if self.current_range == "24h":
            return (now - timedelta(hours=24)).isoformat()
        if self.current_range == "7d":
            return (now - timedelta(days=7)).isoformat()
        if self.current_range == "30d":
            return (now - timedelta(days=30)).isoformat()
        return None

    def _build_connection_points(self, sessions: list[dict]) -> list[tuple[str, int]]:
        if self.current_range == "24h":
            rows = self.db.get_connections_per_hour(24)
            return [(self._format_hour(row["hour"]), int(row["count"])) for row in rows]

        buckets: defaultdict[str, int] = defaultdict(int)
        for session in sessions:
            started_at = session.get("started_at")
            if not started_at:
                continue
            dt = to_local_datetime(started_at)
            if dt is None:
                continue
            buckets[dt.strftime("%m-%d")] += 1
        return sorted(buckets.items())

    @staticmethod
    def _build_service_distribution(sessions: list[dict]) -> list[tuple[str, int]]:
        counter = Counter((session.get("service") or "").lower() for session in sessions)
        return [(key, value) for key, value in counter.items() if key]

    @staticmethod
    def _build_top_ips(sessions: list[dict]) -> list[tuple[str, int]]:
        counter = Counter(session.get("source_ip") for session in sessions if session.get("source_ip"))
        return counter.most_common(10)

    @staticmethod
    def _build_top_credentials(events: list[dict]) -> list[tuple[str, int]]:
        counter = Counter()
        for event in events:
            if event.get("event_type") != "auth_attempt":
                continue
            data = event.get("data") or {}
            counter[f"{data.get('username', '')}:{data.get('password', '')}"] += 1
        return counter.most_common(10)

    @staticmethod
    def _format_hour(timestamp: str) -> str:
        return format_local_hour(timestamp, default=timestamp[-5:])
