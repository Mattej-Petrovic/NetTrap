from __future__ import annotations

import copy

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from nettrap.core.config import save_config
from nettrap.core.database import Database
from nettrap.core.geoip import GeoIPLookup
from nettrap.gui import theme
from nettrap.utils.ip_utils import resolve_bind_host


class ToggleSwitch(QPushButton):
    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(40, 20)
        self._offset = 20.0 if checked else 0.0
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.clicked.connect(self._animate)

    def _animate(self):
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(20.0 if self.isChecked() else 0.0)
        self._animation.start()

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float):
        self._offset = float(value)
        self.update()

    offset = pyqtProperty(float, fget=get_offset, fset=set_offset)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track_color = theme.SUCCESS_ACTIVE if self.isChecked() else theme.INACTIVE_STOPPED
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(track_color))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)
        painter.setBrush(QColor(theme.TEXT_PRIMARY))
        painter.drawEllipse(QRectF(2 + self._offset, 2, 16, 16))


class SectionHeader(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        label = QLabel(title.upper())
        label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 11px; font-weight: 700;"
        )
        left = QFrame()
        left.setFixedHeight(1)
        left.setStyleSheet(f"background: {theme.BORDER_DIVIDERS};")
        right = QFrame()
        right.setFixedHeight(1)
        right.setStyleSheet(f"background: {theme.BORDER_DIVIDERS};")
        layout.addWidget(label)
        layout.addWidget(left, 1)
        layout.addWidget(right, 8)


class SettingsView(QWidget):
    def __init__(
        self,
        db_path: str,
        config: dict,
        service_controller=None,
        on_save_config=None,
        on_database_cleared=None,
        parent=None,
    ):
        super().__init__(parent)
        self.config = copy.deepcopy(config)
        self.db = Database(db_path)
        self.service_controller = service_controller
        self.on_save_config = on_save_config
        self.on_database_cleared = on_database_cleared

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("SETTINGS")
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: 700;"
        )
        self.save_button = QPushButton("Save")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.setStyleSheet(
            f"background: {theme.ACCENT_PRIMARY}; color: {theme.BACKGROUND_MAIN}; border: none; font-weight: 700; padding: 10px 18px;"
        )
        self.save_button.clicked.connect(self.save_settings)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.save_button)
        root.addLayout(header)

        root.addWidget(SectionHeader("Honeypot Services"))
        services_grid = QGridLayout()
        services_grid.setHorizontalSpacing(12)
        services_grid.setVerticalSpacing(12)

        self.ssh_enabled = ToggleSwitch()
        self.ssh_host = QLineEdit()
        self.ssh_port = QLineEdit()
        self.ssh_banner = QLineEdit()
        self.http_enabled = ToggleSwitch()
        self.http_host = QLineEdit()
        self.http_port = QLineEdit()
        self.http_header = QLineEdit()

        for field in (self.ssh_host, self.http_host):
            field.setPlaceholderText("127.0.0.1")
            field.setToolTip(
                "Bind host (default 127.0.0.1): use localhost for local-only testing, "
                "a LAN IPv4 address for one interface, or 0.0.0.0 for all interfaces."
            )

        self._add_service_row(services_grid, 0, "SSH Honeypot", self.ssh_enabled, self.ssh_host, self.ssh_port)
        ssh_banner_label = QLabel("SSH Identification Banner:")
        ssh_banner_label.setToolTip("Value sent as SSH server identification during handshake.")
        self.ssh_banner.setToolTip(
            "Presented SSH server banner string. This affects realism only and does not enable real SSH access."
        )
        services_grid.addWidget(ssh_banner_label, 1, 0)
        services_grid.addWidget(self.ssh_banner, 1, 1, 1, 5)
        ssh_banner_help = QLabel("Displayed to SSH clients as the server identification string.")
        ssh_banner_help.setWordWrap(True)
        ssh_banner_help.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        services_grid.addWidget(ssh_banner_help, 2, 0, 1, 6)
        self._add_service_row(services_grid, 3, "HTTP Honeypot", self.http_enabled, self.http_host, self.http_port)
        http_header_label = QLabel("HTTP Server Header:")
        http_header_label.setToolTip("Value returned in the HTTP Server response header.")
        self.http_header.setToolTip(
            "Presented in the HTTP 'Server' response header to emulate common web server fingerprints."
        )
        services_grid.addWidget(http_header_label, 4, 0)
        services_grid.addWidget(self.http_header, 4, 1, 1, 5)
        http_header_help = QLabel("Returned in HTTP responses as the Server header fingerprint.")
        http_header_help.setWordWrap(True)
        http_header_help.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        services_grid.addWidget(http_header_help, 5, 0, 1, 6)
        host_help = QLabel(
            "Bind host examples: 127.0.0.1 (safe local default), a LAN IPv4 address for one interface, "
            "or 0.0.0.0 to expose on all interfaces."
        )
        host_help.setWordWrap(True)
        host_help.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        services_grid.addWidget(host_help, 6, 0, 1, 6)
        root.addLayout(services_grid)

        root.addWidget(SectionHeader("GeoIP"))
        geo_grid = QGridLayout()
        geo_grid.setHorizontalSpacing(12)
        geo_grid.setVerticalSpacing(12)
        self.geoip_path = QLineEdit()
        self.geoip_browse = QPushButton("Browse...")
        self.geoip_browse.clicked.connect(self._browse_geoip)
        self.geoip_status_dot = QLabel("\u25cf")
        self.geoip_status_label = QLabel("")
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)
        status_row.addWidget(self.geoip_status_dot)
        status_row.addWidget(self.geoip_status_label)
        status_row.addStretch(1)
        geo_grid.addWidget(QLabel("Database path:"), 0, 0)
        geo_grid.addWidget(self.geoip_path, 0, 1)
        geo_grid.addWidget(self.geoip_browse, 0, 2)
        geo_grid.addWidget(QLabel("Status:"), 1, 0)
        geo_grid.addLayout(status_row, 1, 1, 1, 2)
        root.addLayout(geo_grid)

        root.addWidget(SectionHeader("Display"))
        display_grid = QGridLayout()
        display_grid.setHorizontalSpacing(12)
        display_grid.setVerticalSpacing(12)
        self.refresh_slider = QSlider(Qt.Orientation.Horizontal)
        self.refresh_slider.setRange(500, 5000)
        self.refresh_slider.setSingleStep(100)
        self.refresh_slider.setPageStep(100)
        self.refresh_slider.valueChanged.connect(self._update_refresh_label)
        self.refresh_label = QLabel("")
        self.max_feed_items = QLineEdit()
        display_grid.addWidget(QLabel("GUI refresh rate:"), 0, 0)
        display_grid.addWidget(self.refresh_slider, 0, 1)
        display_grid.addWidget(self.refresh_label, 0, 2)
        display_grid.addWidget(QLabel("Max feed items:"), 1, 0)
        display_grid.addWidget(self.max_feed_items, 1, 1)
        root.addLayout(display_grid)

        root.addWidget(SectionHeader("Danger Zone"))
        danger_row = QHBoxLayout()
        self.clear_db_button = QPushButton("Clear Database")
        self.clear_db_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_db_button.setStyleSheet(
            f"background: {theme.ACCENT_ALERTS}; color: {theme.TEXT_PRIMARY}; border: none; font-weight: 700; padding: 10px 16px;"
        )
        self.clear_db_button.clicked.connect(self._clear_database)
        danger_row.addWidget(self.clear_db_button)
        danger_row.addStretch(1)
        root.addLayout(danger_row)
        root.addStretch(1)

        self.geoip_path.textChanged.connect(self._update_geoip_status)
        self._load_from_config()

    def closeEvent(self, event):
        self.db.close()
        super().closeEvent(event)

    def _add_service_row(
        self,
        grid,
        row: int,
        label_text: str,
        toggle: ToggleSwitch,
        host_input: QLineEdit,
        port_input: QLineEdit,
    ):
        grid.addWidget(QLabel(label_text), row, 0)
        grid.addWidget(toggle, row, 1)
        grid.addWidget(QLabel("Host:"), row, 2)
        grid.addWidget(host_input, row, 3)
        grid.addWidget(QLabel("Port:"), row, 4)
        grid.addWidget(port_input, row, 5)

    def _load_from_config(self):
        self.ssh_enabled.setChecked(bool(self.config["services"]["ssh"]["enabled"]))
        self.ssh_enabled.set_offset(20.0 if self.ssh_enabled.isChecked() else 0.0)
        self.ssh_host.setText(str(self.config["services"]["ssh"].get("host", "127.0.0.1")))
        self.ssh_port.setText(str(self.config["services"]["ssh"]["port"]))
        self.ssh_banner.setText(self.config["services"]["ssh"]["banner"])
        self.http_enabled.setChecked(bool(self.config["services"]["http"]["enabled"]))
        self.http_enabled.set_offset(20.0 if self.http_enabled.isChecked() else 0.0)
        self.http_host.setText(str(self.config["services"]["http"].get("host", "127.0.0.1")))
        self.http_port.setText(str(self.config["services"]["http"]["port"]))
        self.http_header.setText(self.config["services"]["http"]["server_header"])
        self.geoip_path.setText(self.config["geoip"]["database_path"])
        self.refresh_slider.setValue(int(self.config["gui"]["refresh_rate_ms"]))
        self.max_feed_items.setText(str(self.config["gui"]["max_feed_items"]))
        self._update_refresh_label(self.refresh_slider.value())
        self._update_geoip_status()

    def _browse_geoip(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select GeoLite2-City.mmdb",
            self.geoip_path.text(),
            "MaxMind DB (*.mmdb);;All Files (*)",
        )
        if path:
            self.geoip_path.setText(path)

    def _update_geoip_status(self):
        lookup = GeoIPLookup(self.geoip_path.text().strip())
        loaded = lookup.available
        lookup.close()
        if loaded:
            self.geoip_status_dot.setStyleSheet(f"color: {theme.SUCCESS_ACTIVE};")
            self.geoip_status_label.setText("Loaded")
        else:
            self.geoip_status_dot.setStyleSheet(f"color: {theme.ACCENT_ALERTS};")
            self.geoip_status_label.setText("Not found")

    def _update_refresh_label(self, value: int):
        self.refresh_label.setText(f"{value}ms")

    def _validated_port(self, value: str) -> int:
        try:
            port = int(value.strip())
        except ValueError as exc:
            raise ValueError("Ports must be numeric.") from exc
        if not 1 <= port <= 65535:
            raise ValueError("Ports must be between 1 and 65535.")
        return port

    def _validated_host(self, value: str) -> str:
        host = value.strip()
        if not host:
            raise ValueError("Bind hosts cannot be empty.")
        resolve_bind_host(host)
        return host

    def save_settings(self):
        try:
            ssh_host = self._validated_host(self.ssh_host.text())
            ssh_port = self._validated_port(self.ssh_port.text())
            http_host = self._validated_host(self.http_host.text())
            http_port = self._validated_port(self.http_port.text())
            max_feed_items = int(self.max_feed_items.text().strip())
            if max_feed_items <= 0:
                raise ValueError("Max feed items must be greater than 0.")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            return

        previous = copy.deepcopy(self.config)
        new_config = copy.deepcopy(self.config)
        new_config["services"]["ssh"]["enabled"] = self.ssh_enabled.isChecked()
        new_config["services"]["ssh"]["host"] = ssh_host
        new_config["services"]["ssh"]["port"] = ssh_port
        new_config["services"]["ssh"]["banner"] = self.ssh_banner.text().strip()
        new_config["services"]["http"]["enabled"] = self.http_enabled.isChecked()
        new_config["services"]["http"]["host"] = http_host
        new_config["services"]["http"]["port"] = http_port
        new_config["services"]["http"]["server_header"] = self.http_header.text().strip()
        new_config["geoip"]["database_path"] = self.geoip_path.text().strip()
        new_config["gui"]["refresh_rate_ms"] = int(self.refresh_slider.value())
        new_config["gui"]["max_feed_items"] = max_feed_items

        restart_required = self._service_restart_required(previous, new_config)
        restart_now = False
        if restart_required and self.service_controller is not None and self.service_controller.any_running():
            response = QMessageBox.question(
                self,
                "Restart Required",
                "Restart services for changes to take effect. Restart now?",
            )
            restart_now = response == QMessageBox.StandardButton.Yes

        save_config(new_config)
        self.config = new_config
        if callable(self.on_save_config):
            self.on_save_config(new_config, restart_now)

        QMessageBox.information(self, "Settings Saved", "Configuration updated successfully.")

    def _clear_database(self):
        response = QMessageBox.question(
            self,
            "Clear Database",
            "Delete all sessions, events, and alerts?",
        )
        if response != QMessageBox.StandardButton.Yes:
            return

        self.db.reset_schema()
        if callable(self.on_database_cleared):
            self.on_database_cleared()
        QMessageBox.information(self, "Database Cleared", "All honeypot data has been removed.")

    @staticmethod
    def _service_restart_required(old: dict, new: dict) -> bool:
        fields = (
            ("services", "ssh", "enabled"),
            ("services", "ssh", "host"),
            ("services", "ssh", "port"),
            ("services", "ssh", "banner"),
            ("services", "http", "enabled"),
            ("services", "http", "host"),
            ("services", "http", "port"),
            ("services", "http", "server_header"),
        )
        for field in fields:
            old_value = old
            new_value = new
            for key in field:
                old_value = old_value[key]
                new_value = new_value[key]
            if old_value != new_value:
                return True
        return False
