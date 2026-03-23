from __future__ import annotations

from PyQt6.QtCore import QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from nettrap.core.database import Database
from nettrap.gui import theme
from nettrap.gui.widgets.event_feed import EventFeed
from nettrap.gui.widgets.stat_card import StatCard


class BarChartCard(QWidget):
    def __init__(self, title: str, items: list[tuple[str, int]] | None = None, parent=None):
        super().__init__(parent)
        self.title = title
        self.items: list[tuple[str, int]] = list(items or [])
        self._tooltip_rows: list[tuple[QRectF, str]] = []
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setObjectName("barChartCard")
        self.setStyleSheet(
            f"""
            QWidget#barChartCard {{
                background: {theme.BACKGROUND_CARDS};
                border: 1px solid {theme.BORDER_DIVIDERS};
                border-radius: 8px;
            }}
            """
        )

    def set_items(self, items: list[tuple[str, int]]):
        self.items = list(items[:6])
        self._tooltip_rows = []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.BACKGROUND_CARDS))
        painter.drawRoundedRect(rect, 8, 8)

        title_font = QFont(theme.FONT_SANS, 11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(theme.TEXT_SECONDARY))
        painter.drawText(16, 28, self.title.upper())
        self._tooltip_rows = []

        if not self.items:
            painter.setPen(QColor(theme.TEXT_SECONDARY))
            painter.drawText(16, 64, "No data")
            return

        max_value = max(value for _, value in self.items) or 1
        top = 54
        bottom_padding = 18
        row_height = max(26, (self.height() - top - bottom_padding) // max(1, len(self.items)))
        label_width = max(140, int(self.width() * 0.40))
        bar_height = 12
        value_width = 44

        label_font = QFont(theme.FONT_MONO, 10)
        painter.setFont(label_font)
        metrics = QFontMetrics(label_font)

        for index, (label, value) in enumerate(self.items):
            y = top + index * row_height
            bar_y = y + (row_height - bar_height) / 2
            label_rect = QRectF(16, y, label_width, row_height)
            bar_x = int(label_rect.right()) + 14
            bar_width = max(36, self.width() - bar_x - value_width - 20)
            ratio = value / max_value
            fill_width = max(10, int(bar_width * ratio))
            value_rect = QRectF(bar_x + bar_width + 8, y, value_width, row_height)
            elided_label = metrics.elidedText(label, Qt.TextElideMode.ElideRight, int(label_width) - 4)
            if elided_label != label:
                text_width = min(metrics.horizontalAdvance(elided_label), int(label_width) - 4)
                text_height = metrics.height()
                text_y = y + (row_height - text_height) / 2
                text_rect = QRectF(label_rect.left(), text_y, max(1, text_width), text_height)
                self._tooltip_rows.append((text_rect, label))

            painter.setPen(QColor(theme.TEXT_PRIMARY))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_label)

            painter.setBrush(QColor("#11161d"))
            painter.setPen(QPen(QColor(theme.BORDER_DIVIDERS), 1))
            painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_width, bar_height), 6, 6)

            painter.setBrush(QColor(theme.ACCENT_PRIMARY))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(bar_x, bar_y, fill_width, bar_height), 6, 6)

            painter.setPen(QColor(theme.TEXT_PRIMARY))
            painter.drawText(value_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, str(value))

    def mouseMoveEvent(self, event):
        pos = event.position()
        for rect, full_text in self._tooltip_rows:
            if rect.contains(pos):
                QToolTip.showText(event.globalPosition().toPoint(), full_text, self)
                return
        QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class DashboardView(QWidget):
    def __init__(self, db_path: str, event_queue, refresh_rate_ms: int, max_feed_items: int, parent=None):
        super().__init__(parent)
        self.event_queue = event_queue
        self.db = Database(db_path)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.active_sessions_card = StatCard("\u25ce", "0", "Active Sessions")
        self.connections_card = StatCard("\u21ba", "0", "Conn/Hour")
        self.unique_ips_card = StatCard("\u25cc", "0", "Unique IPs")
        self.alerts_card = StatCard("!", "0", "Alerts")
        for card in (
            self.active_sessions_card,
            self.connections_card,
            self.unique_ips_card,
            self.alerts_card,
        ):
            stats_row.addWidget(card, 1)

        self.feed = EventFeed(max_items=max_feed_items)
        self.credentials_chart = BarChartCard("Top Credentials")
        self.user_agents_chart = BarChartCard("Top User-Agents")

        right_column = QVBoxLayout()
        right_column.setSpacing(12)
        right_column.addWidget(self.credentials_chart, 1)
        right_column.addWidget(self.user_agents_chart, 1)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)
        bottom_row.addWidget(self.feed, 3)

        charts_widget = QWidget()
        charts_widget.setLayout(right_column)
        bottom_row.addWidget(charts_widget, 2)

        self.bottom_widget = QWidget()
        self.bottom_widget.setLayout(bottom_row)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)
        root.addLayout(stats_row)
        self.empty_state = QLabel("No sessions recorded yet. Waiting for connections...")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 16px; font-weight: 600; padding: 18px 0;"
        )
        root.addWidget(self.empty_state)
        root.addWidget(self.bottom_widget, 1)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(refresh_rate_ms)
        self.refresh_timer.timeout.connect(self.refresh_metrics)
        self.refresh_timer.start()

        self.refresh_metrics()

    def set_active(self, active: bool):
        if active:
            if not self.refresh_timer.isActive():
                self.refresh_timer.start()
            self.refresh_metrics()
        else:
            self.refresh_timer.stop()

    def refresh_metrics(self):
        self.active_sessions_card.update_value(str(self.db.get_active_sessions_count()))
        connections = self.db.get_connections_per_hour(hours=1)
        self.connections_card.update_value(str(sum(int(row["count"]) for row in connections)))
        self.unique_ips_card.update_value(str(self.db.get_unique_ips_count(hours=24)))
        self.alerts_card.update_value(str(self.db.get_alerts_count()))
        self.credentials_chart.set_items(
            [(row["credential"], int(row["count"])) for row in self.db.get_top_credentials(limit=6)]
        )
        self.user_agents_chart.set_items(
            [(row["user_agent"], int(row["count"])) for row in self.db.get_top_user_agents(limit=6)]
        )
        has_sessions = self.db.get_total_sessions_count() > 0
        self.empty_state.setVisible(not has_sessions)
        self.bottom_widget.setVisible(has_sessions)

    def on_new_event(self, event: dict):
        self.feed.add_event(event["timestamp"], event["service"], event["summary"])
        self.refresh_metrics()

    def closeEvent(self, event):
        try:
            self.refresh_timer.stop()
            self.db.close()
        finally:
            super().closeEvent(event)
