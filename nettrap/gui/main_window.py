from __future__ import annotations

from queue import Empty

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from nettrap.core.geoip import GeoIPLookup
from nettrap.gui import theme
from nettrap.gui.views.analytics import AnalyticsView
from nettrap.gui.views.dashboard import DashboardView
from nettrap.gui.views.export import ExportView
from nettrap.gui.views.live_map import LiveMapView
from nettrap.gui.views.sessions import SessionsView
from nettrap.gui.views.settings import SettingsView


class MainWindow(QMainWindow):
    def __init__(self, config, event_queue, service_manager=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.event_queue = event_queue
        self.service_manager = service_manager
        self.sidebar_buttons: list[QPushButton] = []
        self.sidebar_labels: list[str] = []
        self.status_widgets: dict[str, tuple[QLabel, QLabel]] = {}
        self.db_path = config["database"]["path"]
        self.refresh_rate_ms = int(config["gui"]["refresh_rate_ms"])
        self.max_feed_items = int(config["gui"]["max_feed_items"])

        self.setWindowTitle("NetTrap \u2014 Honeypot Monitor")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 700)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        self.sidebar = self._build_sidebar()
        self.sidebar.setFixedWidth(220)
        root.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background: {theme.BACKGROUND_MAIN};")
        root.addWidget(self.stack, 1)

        self._build_pages()

        self._queue_timer = QTimer(self)
        self._queue_timer.setInterval(100)
        self._queue_timer.timeout.connect(self._dispatch_queue_events)
        self._queue_timer.start()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self._update_service_statuses)
        self._status_timer.start()

        self._set_page(0)
        self._update_service_statuses()

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setStyleSheet(f"background: {theme.BACKGROUND_SIDEBAR};")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 24, 0, 24)
        layout.setSpacing(0)

        branding = QLabel("NETTRAP")
        branding.setStyleSheet(
            f"color: {theme.ACCENT_PRIMARY}; font-size: 16px; font-weight: 800; padding: 0 24px;"
        )
        version = QLabel("v1.0.0")
        version.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 11px; padding: 2px 24px 0 24px;"
        )

        layout.addWidget(branding)
        layout.addWidget(version)
        layout.addSpacing(18)
        layout.addWidget(self._divider())

        for text, index in (
            ("Dashboard", 0),
            ("Live Map", 1),
            ("Sessions", 2),
            ("Analytics", 3),
        ):
            layout.addWidget(self._nav_button(text, index))

        layout.addSpacing(12)
        layout.addWidget(self._divider())

        for text, index in (("Settings", 4), ("Export", 5)):
            layout.addWidget(self._nav_button(text, index))

        layout.addSpacing(12)
        layout.addWidget(self._divider())
        layout.addStretch(1)
        layout.addWidget(self._status_row("ssh", "SSH"))
        layout.addWidget(self._status_row("http", "HTTP"))
        layout.addSpacing(12)

        self.stop_start_button = QPushButton("Start All")
        self.stop_start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_start_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.stop_start_button.setFixedWidth(172)
        self.stop_start_button.setStyleSheet(
            f"background: {theme.SUCCESS_ACTIVE}; color: {theme.BACKGROUND_MAIN}; border: none; font-weight: 700;"
        )
        self.stop_start_button.clicked.connect(self._toggle_services)
        layout.addWidget(self.stop_start_button)
        layout.setAlignment(self.stop_start_button, Qt.AlignmentFlag.AlignHCenter)
        return sidebar

    def _build_pages(self):
        self.dashboard_view = DashboardView(
            self.db_path,
            None,
            self.refresh_rate_ms,
            self.max_feed_items,
        )
        self.live_map_view = LiveMapView(self.db_path, self.config)
        self.sessions_view = SessionsView(self.db_path, self.refresh_rate_ms, None)
        self.analytics_view = AnalyticsView(self.db_path, self.refresh_rate_ms)
        self.settings_view = SettingsView(
            self.db_path,
            self.config,
            service_controller=self.service_manager,
            on_save_config=self._handle_config_saved,
            on_database_cleared=self._handle_database_cleared,
        )
        self.export_view = ExportView(self.db_path, self.config)

        for widget in (
            self.dashboard_view,
            self.live_map_view,
            self.sessions_view,
            self.analytics_view,
            self.settings_view,
            self.export_view,
        ):
            self.stack.addWidget(widget)

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(
            f"color: {theme.BORDER_DIVIDERS}; background: {theme.BORDER_DIVIDERS}; max-height: 1px;"
        )
        return line

    def _nav_button(self, text: str, index: int) -> QPushButton:
        button = QPushButton(f"\u25cb {text}")
        button.setObjectName("navButton")
        button.setProperty("navActive", False)
        button.setProperty("navLabel", text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda checked=False, idx=index: self._set_page(idx))
        self.sidebar_buttons.append(button)
        self.sidebar_labels.append(text)
        return button

    def _status_row(self, service_key: str, label_text: str) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(24, 6, 24, 0)
        row_layout.setSpacing(8)

        dot = QLabel("\u25cf")
        label = QLabel(f"{label_text}: Stopped")
        dot.setStyleSheet(f"color: {theme.ACCENT_ALERTS}; font-size: 12px;")
        label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
        row_layout.addWidget(dot)
        row_layout.addWidget(label)
        row_layout.addStretch(1)
        self.status_widgets[service_key] = (dot, label)
        return row

    def _set_page(self, index: int):
        self.stack.setCurrentIndex(index)
        for page_index in range(self.stack.count()):
            widget = self.stack.widget(page_index)
            if hasattr(widget, "set_active"):
                widget.set_active(page_index == index)
        for button_index, button in enumerate(self.sidebar_buttons):
            active = button_index == index
            label = str(button.property("navLabel") or self.sidebar_labels[button_index])
            button.setText(f"{'\u25cf' if active else '\u25cb'} {label}")
            button.setProperty("navActive", active)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _dispatch_queue_events(self):
        if self.event_queue is None:
            return

        while True:
            try:
                event = self.event_queue.get_nowait()
            except Empty:
                break
            except Exception:
                break
            else:
                self.dashboard_view.on_new_event(event)
                self.live_map_view.on_new_event(event)

    def _update_service_statuses(self):
        for service_key, (_, label) in self.status_widgets.items():
            running = bool(self.service_manager and self.service_manager.is_running(service_key))
            dot, label = self.status_widgets[service_key]
            color = theme.SUCCESS_ACTIVE if running else theme.ACCENT_ALERTS
            state = "Running" if running else "Stopped"
            dot.setStyleSheet(f"color: {color}; font-size: 12px;")
            label.setText(f"{service_key.upper()}: {state}")
            label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")

        running_any = bool(self.service_manager and self.service_manager.any_running())
        if running_any:
            self.stop_start_button.setText("Stop All")
            self.stop_start_button.setStyleSheet(
                f"background: {theme.ACCENT_ALERTS}; color: {theme.TEXT_PRIMARY}; border: none; font-weight: 700;"
            )
        else:
            self.stop_start_button.setText("Start All")
            self.stop_start_button.setStyleSheet(
                f"background: {theme.SUCCESS_ACTIVE}; color: {theme.BACKGROUND_MAIN}; border: none; font-weight: 700;"
            )

    def _toggle_services(self):
        if self.service_manager is None:
            return
        try:
            if self.service_manager.any_running():
                self.service_manager.stop_all()
            else:
                self.service_manager.start_enabled_services()
        except Exception as exc:
            QMessageBox.warning(self, "Service Control", str(exc))
        finally:
            self._update_service_statuses()

    def _handle_config_saved(self, new_config: dict, restart_now: bool):
        self.config = new_config
        self.refresh_rate_ms = int(new_config["gui"]["refresh_rate_ms"])
        self.max_feed_items = int(new_config["gui"]["max_feed_items"])
        self.settings_view.config = new_config
        if self.service_manager is not None:
            self.service_manager.update_config(new_config)
            if restart_now:
                self.service_manager.restart_all()

        self.dashboard_view.refresh_timer.setInterval(self.refresh_rate_ms)
        self.dashboard_view.feed.max_items = self.max_feed_items
        self.sessions_view.refresh_timer.setInterval(self.refresh_rate_ms)
        self.analytics_view.refresh_timer.setInterval(self.refresh_rate_ms)
        self.live_map_view.refresh_timer.setInterval(self.refresh_rate_ms)
        self.live_map_view.config = new_config
        self.live_map_view.geoip.close()
        self.live_map_view.geoip = GeoIPLookup(new_config["geoip"]["database_path"])
        self.live_map_view._banner_visible = not self.live_map_view.geoip.available
        self.live_map_view.banner.setVisible(self.live_map_view._banner_visible)
        self.live_map_view._position_overlays()
        self.export_view.config = new_config
        self.dashboard_view.refresh_metrics()
        self.sessions_view.refresh()
        self.analytics_view.refresh()
        self.live_map_view.refresh_map()
        self.export_view.refresh_preview()
        self._update_service_statuses()

    def _handle_database_cleared(self):
        self.dashboard_view.refresh_metrics()
        self.sessions_view.refresh()
        self.analytics_view.refresh()
        self.live_map_view.refresh_map()
        self.export_view.refresh_preview()

    def closeEvent(self, event):
        response = QMessageBox.question(
            self,
            "Exit NetTrap",
            "Stop all services and close NetTrap?",
        )
        if response != QMessageBox.StandardButton.Yes:
            event.ignore()
            return

        self._queue_timer.stop()
        self._status_timer.stop()
        if self.service_manager is not None:
            self.service_manager.stop_all()
        for index in range(self.stack.count()):
            widget = self.stack.widget(index)
            if widget is not None:
                widget.close()
        event.accept()
