"""NetTrap - Honeypot Monitor"""
from __future__ import annotations

import multiprocessing
import os
import signal
import socket
import sys
from copy import deepcopy
from pathlib import Path

from nettrap.core.config import get_config, get_config_path, get_last_config_error
from nettrap.core.database import Database
from nettrap.core.geoip import GeoIPLookup
from nettrap.core.logger import JsonLogger
from nettrap.honeypots.http_honeypot import HTTPHoneypot
from nettrap.honeypots.ssh_honeypot import SSHHoneypot
from nettrap.utils.ip_utils import resolve_bind_host


def _ensure_runtime_directories(config: dict) -> None:
    Path(config["database"]["path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(config["logging"]["json_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["export"]["default_directory"]).mkdir(parents=True, exist_ok=True)
    Path(config["geoip"]["database_path"]).parent.mkdir(parents=True, exist_ok=True)


def _check_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((resolve_bind_host(host), port))


def _check_service_ports(config: dict) -> tuple[str, str, int] | None:
    for service_name in ("ssh", "http"):
        service = config["services"].get(service_name, {})
        if not service.get("enabled", False):
            continue
        host = str(service.get("host", "127.0.0.1"))
        port = int(service["port"])
        try:
            _check_port_available(host, port)
        except OSError:
            return service_name, host, port
    return None


def _check_privileges(config: dict) -> None:
    if os.name == "nt" or not hasattr(os, "getuid"):
        return

    uid = os.getuid()
    for service_name in ("ssh", "http"):
        service = config["services"].get(service_name, {})
        if not service.get("enabled", False):
            continue
        port = int(service["port"])
        if port < 1024 and uid != 0:
            raise PermissionError(f"Port {port} requires elevated privileges.")


def run_ssh(config, event_queue):
    db = Database(config["database"]["path"])
    logger = JsonLogger(config["logging"]["json_dir"])
    geoip = GeoIPLookup(config["geoip"]["database_path"])
    ssh = SSHHoneypot(
        host=config["services"]["ssh"].get("host", "127.0.0.1"),
        port=config["services"]["ssh"]["port"],
        db=db,
        logger=logger,
        banner=config["services"]["ssh"]["banner"],
        event_queue=event_queue,
        geoip=geoip,
    )
    try:
        ssh.start()
    finally:
        geoip.close()
        db.close()


def run_http(config, event_queue):
    db = Database(config["database"]["path"])
    logger = JsonLogger(config["logging"]["json_dir"])
    geoip = GeoIPLookup(config["geoip"]["database_path"])
    http = HTTPHoneypot(
        host=config["services"]["http"].get("host", "127.0.0.1"),
        port=config["services"]["http"]["port"],
        db=db,
        logger=logger,
        server_header=config["services"]["http"]["server_header"],
        page_profile=config["services"]["http"].get("page_profile", "admin"),
        trust_proxy_headers=config["services"]["http"].get("trust_proxy_headers", False),
        debug_proxy_resolution=config["services"]["http"].get("debug_proxy_resolution", False),
        config_path=str(get_config_path()),
        event_queue=event_queue,
        geoip=geoip,
    )
    try:
        http.start()
    finally:
        geoip.close()
        db.close()


class ServiceManager:
    def __init__(self, config: dict, event_queue):
        self._config = deepcopy(config)
        self._event_queue = event_queue
        self._processes: dict[str, multiprocessing.Process | None] = {
            "ssh": None,
            "http": None,
        }

    def update_config(self, config: dict):
        self._config = deepcopy(config)
        _ensure_runtime_directories(self._config)

    def reload_config(self):
        get_config.cache_clear()
        self.update_config(get_config())

    def statuses(self) -> dict[str, bool]:
        return {
            name: bool(process is not None and process.is_alive())
            for name, process in self._processes.items()
        }

    def is_running(self, service_key: str) -> bool:
        process = self._processes.get(service_key)
        return bool(process is not None and process.is_alive())

    def any_running(self) -> bool:
        return any(self.statuses().values())

    def _enabled_services(self) -> list[str]:
        return [
            name
            for name in ("ssh", "http")
            if self._config["services"].get(name, {}).get("enabled", False)
        ]

    def _check_ports(self):
        for service_name in self._enabled_services():
            if self.is_running(service_name):
                continue
            service = self._config["services"][service_name]
            _check_port_available(
                str(service.get("host", "127.0.0.1")),
                int(service["port"]),
            )

    def _start_service(self, service_name: str):
        target = run_ssh if service_name == "ssh" else run_http
        process = multiprocessing.Process(
            target=target,
            args=(self._config, self._event_queue),
            daemon=True,
        )
        process.start()
        self._processes[service_name] = process
        process.join(timeout=0.3)
        if process.exitcode is not None:
            self._processes[service_name] = None
            raise RuntimeError(f"{service_name.upper()} failed to start.")

    def start_enabled_services(self):
        self.reload_config()
        _ensure_runtime_directories(self._config)
        _check_privileges(self._config)
        try:
            self._check_ports()
        except OSError as exc:
            conflict = _check_service_ports(self._config)
            if conflict is not None:
                service_name, host, port = conflict
                raise OSError(f"{service_name.upper()} bind {host}:{port} is already in use.") from exc
            raise
        started: list[str] = []
        try:
            for service_name in self._enabled_services():
                if self.is_running(service_name):
                    continue
                self._start_service(service_name)
                started.append(service_name)
        except Exception:
            self.stop_all()
            raise

    def stop_all(self):
        for service_name, process in list(self._processes.items()):
            if process is None:
                continue
            try:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
                if process.is_alive() and hasattr(process, "kill"):
                    process.kill()
                    process.join(timeout=5)
            except Exception:
                pass
            self._processes[service_name] = None

    def restart_all(self):
        self.stop_all()
        self.start_enabled_services()


def main():
    try:
        from PyQt6.QtGui import QIcon
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        print("ERROR: PyQt6 not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    config = get_config()
    config_error = get_last_config_error()
    if config_error:
        print(f"ERROR: Malformed config.yaml: {config_error}")
        print("Using defaults.")

    _ensure_runtime_directories(config)

    from nettrap.gui.app import create_app
    from nettrap.gui.main_window import MainWindow
    from nettrap.core.runtime import resource_path

    app = create_app()
    icon_path = resource_path("assets", "nettrap.ico")
    app_icon = QIcon(str(icon_path))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    event_queue = multiprocessing.Queue()
    service_manager = ServiceManager(config, event_queue)

    window = MainWindow(config, event_queue, service_manager=service_manager)
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()

    def _shutdown(*_args):
        service_manager.stop_all()
        app.quit()

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)
    app.aboutToQuit.connect(service_manager.stop_all)

    try:
        exit_code = app.exec()
    finally:
        service_manager.stop_all()

    sys.exit(exit_code)


def _run_webengine_load_guard() -> int:
    try:
        from PyQt6.QtCore import QTimer, QUrl
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    except Exception:
        return 1

    from nettrap.core.runtime import resource_path
    from nettrap.gui.app import create_app

    map_path = resource_path("assets", "map.html")
    if not map_path.exists():
        return 2

    app = create_app()
    view = QWebEngineView()
    guard = {"render_terminated": False}

    def _mark_failed(*_args) -> None:
        guard["render_terminated"] = True
        app.quit()

    view.renderProcessTerminated.connect(_mark_failed)
    view.load(QUrl.fromLocalFile(str(map_path)))
    QTimer.singleShot(1200, app.quit)
    app.exec()
    return 0 if not guard["render_terminated"] else 3


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--nettrap-http-only" in sys.argv:
        run_http(get_config(), None)
        sys.exit(0)
    if "--nettrap-webengine-load-guard" in sys.argv:
        sys.exit(_run_webengine_load_guard())
    main()
