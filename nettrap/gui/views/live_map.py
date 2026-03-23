from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from nettrap.core.database import Database
from nettrap.core.geoip import GeoIPLookup
from nettrap.core.runtime import is_frozen, project_root, resource_path
from nettrap.gui import theme
from nettrap.utils.time_utils import format_local_time


@lru_cache(maxsize=1)
def _webengine_load_guard() -> tuple[bool, str]:
    if is_frozen():
        command = [sys.executable, "--nettrap-webengine-load-guard"]
    else:
        command = [sys.executable, str(project_root() / "main.py"), "--nettrap-webengine-load-guard"]

    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "timeout": 10,
        "check": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        result = subprocess.run(command, **kwargs)
    except Exception as exc:
        return False, f"launch_failed: {exc}"

    if result.returncode == 0:
        return True, "ok"
    return False, f"exit_code: {result.returncode}"


class _MapAssetRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args) -> None:  # noqa: A003 - matches base class signature
        return


class _MapRequestInterceptor:  # type: ignore[misc]
    def __init__(self):
        from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor

        class _Interceptor(QWebEngineUrlRequestInterceptor):
            request_observed = pyqtSignal(dict)

            def interceptRequest(self, info):
                url = info.requestUrl().toString()
                payload = {
                    "url": url,
                    "resource_type": getattr(info.resourceType(), "name", str(info.resourceType())),
                    "first_party_url": info.firstPartyUrl().toString(),
                    "method": bytes(info.requestMethod()).decode("utf-8", errors="replace"),
                }
                self.request_observed.emit(payload)

        self._impl = _Interceptor()
        self.request_observed = self._impl.request_observed

    def bind_to_profile(self, profile) -> None:
        profile.setUrlRequestInterceptor(self._impl)


class _MapPage:  # type: ignore[misc]
    def __init__(self, profile, parent=None):
        from PyQt6.QtWebEngineCore import QWebEnginePage

        class _Page(QWebEnginePage):
            console_message = pyqtSignal(dict)
            certificate_error = pyqtSignal(dict)

            def javaScriptConsoleMessage(self, level, message, line_number, source_id):
                payload = {
                    "level": getattr(level, "name", str(level)),
                    "message": message,
                    "line": int(line_number),
                    "source": source_id,
                }
                self.console_message.emit(payload)
                super().javaScriptConsoleMessage(level, message, line_number, source_id)

            def certificateError(self, error):
                payload = {
                    "description": error.description(),
                    "url": error.url().toString(),
                    "is_overridable": bool(error.isOverridable()),
                    "type": getattr(error.type(), "name", str(error.type())),
                }
                self.certificate_error.emit(payload)
                return super().certificateError(error)

        self._impl = _Page(profile, parent)
        self.console_message = self._impl.console_message
        self.certificate_error = self._impl.certificate_error

    @property
    def page(self):
        return self._impl


class LiveMapView(QWidget):
    LOAD_TIMEOUT_MS = 8000
    PAGE_PROBE_TIMEOUT_MS = 2000

    def __init__(self, db_path: str, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.db = Database(db_path)
        self.geoip = GeoIPLookup(config["geoip"]["database_path"])
        self._headless = os.environ.get("QT_QPA_PLATFORM", "").lower() in {"offscreen", "minimal"}
        self._map_initialized = False
        self._interactive_map_available = False
        self._page_ready = False
        self._banner_visible = not self.geoip.available
        self._last_marker_ips: set[str] = set()
        self.web_view = None
        self._diagnostics: dict[str, object] = {}
        self._asset_server: ThreadingHTTPServer | None = None
        self._asset_server_thread: threading.Thread | None = None
        self._asset_server_root: Path | None = None
        self._asset_server_base_url = ""
        self._request_interceptor = None
        self._web_profile = None
        self._map_page = None

        self._load_timeout = QTimer(self)
        self._load_timeout.setSingleShot(True)
        self._load_timeout.setInterval(self.LOAD_TIMEOUT_MS)
        self._load_timeout.timeout.connect(self._on_load_timeout)

        self._page_probe_timeout = QTimer(self)
        self._page_probe_timeout.setSingleShot(True)
        self._page_probe_timeout.setInterval(self.PAGE_PROBE_TIMEOUT_MS)
        self._page_probe_timeout.timeout.connect(self._on_page_probe_timeout)

        self._reset_diagnostics()

        self.banner = self._build_banner()
        self.empty_state = QLabel("No geo-located sessions yet.")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 16px; font-weight: 600; background: transparent;"
        )

        self.map_shell = QWidget()
        self.map_shell.setStyleSheet("background: #0D1117;")
        self.shell_layout = QVBoxLayout(self.map_shell)
        self.shell_layout.setContentsMargins(0, 0, 0, 0)
        self.shell_layout.setSpacing(0)
        self._map_widget = self._build_status_widget(
            "Live map loads on demand",
            "Open the Live Map tab to initialize the embedded browser.",
        )
        self.shell_layout.addWidget(self._map_widget, 1)

        self.banner.setParent(self.map_shell)
        self.empty_state.setParent(self.map_shell)
        self.banner.setVisible(not self.geoip.available)
        self.empty_state.hide()
        self.banner.raise_()
        self.empty_state.raise_()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(0)
        root.addWidget(self.map_shell, 1)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(int(config["gui"]["refresh_rate_ms"]))
        self.refresh_timer.timeout.connect(self.refresh_map)
        self.refresh_timer.start()

    def _build_status_widget(self, title_text: str, body_text: str) -> QWidget:
        placeholder = QFrame()
        placeholder.setStyleSheet(
            f"""
            QFrame {{
                background: #0D1117;
                border: 1px solid {theme.BORDER_DIVIDERS};
                border-radius: 8px;
            }}
            """
        )
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
        title = QLabel(title_text)
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: 700;"
        )
        body = QLabel(body_text)
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(1)
        return placeholder

    def _map_asset_paths(self) -> dict[str, Path]:
        map_path = resource_path("assets", "map.html")
        assets_root = map_path.parent
        return {
            "map_html": map_path,
            "map_js": assets_root / "map.js",
            "map_css": assets_root / "map.css",
            "leaflet_js": assets_root / "vendor" / "leaflet" / "leaflet.js",
            "leaflet_css": assets_root / "vendor" / "leaflet" / "leaflet.css",
        }

    def _start_asset_server(self, assets_root: Path) -> str:
        if (
            self._asset_server is not None
            and self._asset_server_thread is not None
            and self._asset_server_thread.is_alive()
            and self._asset_server_root == assets_root
            and self._asset_server_base_url
        ):
            return self._asset_server_base_url

        self._stop_asset_server()

        handler_factory = lambda *args, **kwargs: _MapAssetRequestHandler(  # noqa: E731
            *args,
            directory=str(assets_root),
            **kwargs,
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        self._asset_server = server
        self._asset_server_thread = thread
        self._asset_server_root = assets_root
        self._asset_server_base_url = f"http://127.0.0.1:{server.server_port}"
        return self._asset_server_base_url

    def _stop_asset_server(self) -> None:
        if self._asset_server is None:
            self._asset_server_thread = None
            self._asset_server_root = None
            self._asset_server_base_url = ""
            return

        try:
            self._asset_server.shutdown()
            self._asset_server.server_close()
        except Exception:
            pass

        if self._asset_server_thread is not None:
            self._asset_server_thread.join(timeout=1)

        self._asset_server = None
        self._asset_server_thread = None
        self._asset_server_root = None
        self._asset_server_base_url = ""

    def _reset_diagnostics(self) -> None:
        asset_paths = self._map_asset_paths()
        self._diagnostics = {
            "mode": "frozen" if is_frozen() else "source",
            "map_path": str(asset_paths["map_html"]),
            "map_exists": asset_paths["map_html"].exists(),
            "map_js_exists": asset_paths["map_js"].exists(),
            "map_css_exists": asset_paths["map_css"].exists(),
            "leaflet_js_exists": asset_paths["leaflet_js"].exists(),
            "leaflet_css_exists": asset_paths["leaflet_css"].exists(),
            "load_started": False,
            "load_finished": None,
            "render_process_terminated": False,
            "render_termination_status": "",
            "render_exit_code": None,
            "last_url": "",
            "map_load_strategy": "",
            "asset_server_base_url": "",
            "asset_server_error": "",
            "load_timeout": False,
            "page_probe_timeout": False,
            "page_probe_completed": False,
            "leaflet_available": None,
            "map_api_available": None,
            "webengine_local_remote_urls": None,
            "webengine_local_file_urls": None,
            "local_file_access_blocked": None,
            "tile_request_count": 0,
            "tile_request_urls": [],
            "js_console_errors": [],
            "certificate_errors": [],
            "js_probe_summary": "",
            "browser_init_error": "",
            "crash_guard_ok": None,
            "crash_guard_reason": "",
        }

    def _diagnostic_lines(self) -> list[str]:
        diagnostics = self._diagnostics
        lines = [
            f"mode: {diagnostics['mode']}",
            f"map_path: {diagnostics['map_path']}",
            f"map.html exists: {diagnostics['map_exists']}",
            f"map.js exists: {diagnostics['map_js_exists']}",
            f"map.css exists: {diagnostics['map_css_exists']}",
            f"leaflet.js exists: {diagnostics['leaflet_js_exists']}",
            f"leaflet.css exists: {diagnostics['leaflet_css_exists']}",
            f"loadStarted: {diagnostics['load_started']}",
            f"loadFinished: {diagnostics['load_finished']}",
            f"renderProcessTerminated: {diagnostics['render_process_terminated']}",
            f"local_file_access_blocked: {diagnostics['local_file_access_blocked']}",
        ]
        if diagnostics["last_url"]:
            lines.append(f"last_url: {diagnostics['last_url']}")
        if diagnostics["map_load_strategy"]:
            lines.append(f"map_load_strategy: {diagnostics['map_load_strategy']}")
        if diagnostics["asset_server_base_url"]:
            lines.append(f"asset_server_base_url: {diagnostics['asset_server_base_url']}")
        if diagnostics["asset_server_error"]:
            lines.append(f"asset_server_error: {diagnostics['asset_server_error']}")
        if diagnostics["render_termination_status"]:
            lines.append(f"render_status: {diagnostics['render_termination_status']}")
        if diagnostics["render_exit_code"] is not None:
            lines.append(f"render_exit_code: {diagnostics['render_exit_code']}")
        if diagnostics["webengine_local_remote_urls"] is not None:
            lines.append(
                f"webengine_local_remote_urls: {diagnostics['webengine_local_remote_urls']}"
            )
        if diagnostics["webengine_local_file_urls"] is not None:
            lines.append(
                f"webengine_local_file_urls: {diagnostics['webengine_local_file_urls']}"
            )
        if diagnostics["leaflet_available"] is not None:
            lines.append(f"leaflet_available: {diagnostics['leaflet_available']}")
        if diagnostics["map_api_available"] is not None:
            lines.append(f"map_api_available: {diagnostics['map_api_available']}")
        if diagnostics["tile_request_count"]:
            lines.append(f"tile_request_count: {diagnostics['tile_request_count']}")
        if diagnostics["tile_request_urls"]:
            lines.append(f"tile_request_urls: {json.dumps(diagnostics['tile_request_urls'])}")
        if diagnostics["js_console_errors"]:
            lines.append(f"js_console_errors: {json.dumps(diagnostics['js_console_errors'])}")
        if diagnostics["certificate_errors"]:
            lines.append(f"certificate_errors: {json.dumps(diagnostics['certificate_errors'])}")
        if diagnostics["load_timeout"]:
            lines.append("load_timeout: True")
        if diagnostics["page_probe_timeout"]:
            lines.append("page_probe_timeout: True")
        if diagnostics["browser_init_error"]:
            lines.append(f"browser_init_error: {diagnostics['browser_init_error']}")
        if diagnostics["crash_guard_ok"] is not None:
            lines.append(f"crash_guard_ok: {diagnostics['crash_guard_ok']}")
        if diagnostics["crash_guard_reason"]:
            lines.append(f"crash_guard_reason: {diagnostics['crash_guard_reason']}")
        if diagnostics["js_probe_summary"]:
            lines.append(f"js_probe: {diagnostics['js_probe_summary']}")
        return lines

    def _log_diagnostics(self, title_text: str) -> None:
        print(
            f"[NetTrap LiveMap] {title_text}\n" + "\n".join(self._diagnostic_lines()),
            file=sys.stderr,
        )

    def _show_map_failure(self, title_text: str, body_text: str) -> None:
        diagnostics = "\n".join(self._diagnostic_lines())
        self._log_diagnostics(title_text)
        self._show_map_status(title_text, f"{body_text}\n\n{diagnostics}")

    def _create_web_view(self) -> QWidget:
        from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        view = QWebEngineView()
        profile = QWebEngineProfile(view)
        interceptor = _MapRequestInterceptor()
        interceptor.bind_to_profile(profile)
        interceptor.request_observed.connect(self._on_request_observed)

        page_wrapper = _MapPage(profile, view)
        page_wrapper.console_message.connect(self._on_console_message)
        page_wrapper.certificate_error.connect(self._on_certificate_error)
        view.setPage(page_wrapper.page)

        disable_remote_override = os.environ.get("NETTRAP_MAP_DISABLE_REMOTE_ACCESS", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if not disable_remote_override:
            view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                True,
            )
        self._diagnostics["webengine_local_remote_urls"] = view.settings().testAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls
        )
        self._diagnostics["webengine_local_file_urls"] = view.settings().testAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls
        )

        self._web_profile = profile
        self._request_interceptor = interceptor
        self._map_page = page_wrapper.page
        view.loadStarted.connect(self._on_load_started)
        view.loadFinished.connect(self._on_load_finished)
        view.urlChanged.connect(self._on_url_changed)
        view.renderProcessTerminated.connect(self._on_render_process_terminated)
        return view

    def _set_map_widget(self, widget: QWidget) -> None:
        current = self._map_widget
        if current is widget:
            return
        self.shell_layout.removeWidget(current)
        current.setParent(None)
        current.deleteLater()
        self._map_widget = widget
        self.shell_layout.insertWidget(0, widget, 1)
        self.banner.raise_()
        self.empty_state.raise_()

    def _show_map_status(self, title_text: str, body_text: str) -> None:
        self._load_timeout.stop()
        self._page_probe_timeout.stop()
        self._stop_asset_server()
        self.web_view = None
        self._map_page = None
        self._request_interceptor = None
        self._web_profile = None
        self._interactive_map_available = False
        self._page_ready = False
        self.empty_state.hide()
        self._set_map_widget(self._build_status_widget(title_text, body_text))
        self._position_overlays()

    def _initialize_map(self) -> None:
        if self._map_initialized:
            return
        self._map_initialized = True
        self._reset_diagnostics()

        if self._headless:
            self._show_map_failure(
                "Leaflet map disabled in headless mode",
                "The interactive map uses QWebEngineView and loads normally in the desktop app.",
            )
            return

        guard_ok, guard_reason = _webengine_load_guard()
        self._diagnostics["crash_guard_ok"] = guard_ok
        self._diagnostics["crash_guard_reason"] = guard_reason
        if not guard_ok:
            self._show_map_failure(
                "Live map unavailable on this system",
                "NetTrap blocked the embedded map load because QWebEngine crashed during an isolated preflight check.",
            )
            return

        try:
            web_view = self._create_web_view()
        except Exception as exc:
            self._diagnostics["browser_init_error"] = str(exc)
            self._show_map_failure(
                "Live map browser failed to initialize",
                f"The embedded browser could not start: {exc}",
            )
            return

        self.web_view = web_view
        self._interactive_map_available = True
        self._set_map_widget(web_view)
        self._load_map()

    def _build_banner(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            f"""
            QFrame {{
                background: rgba(8, 12, 17, 0.88);
                border: 1px solid {theme.BORDER_DIVIDERS};
                border-radius: 12px;
            }}
            """
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        icon = QWidget()
        icon.setFixedSize(12, 12)
        icon.setStyleSheet(f"background: {theme.ACCENT_PRIMARY}; border-radius: 6px;")

        text = QWidget()
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        title = QLabel("GeoIP database not found")
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-weight: 700; font-size: 13px;"
        )
        body = QLabel(
            "Download free from maxmind.com and place GeoLite2-City.mmdb in data/ folder."
        )
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        text_layout.addWidget(title)
        text_layout.addWidget(body)

        dismiss = QPushButton("Dismiss")
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.clicked.connect(self._dismiss_banner)

        layout.addWidget(icon)
        layout.addWidget(text, 1)
        layout.addWidget(dismiss)
        return frame

    def _load_map(self):
        if self.web_view is None:
            return

        crash_guard_ok = self._diagnostics.get("crash_guard_ok")
        crash_guard_reason = self._diagnostics.get("crash_guard_reason")
        self._reset_diagnostics()
        self._diagnostics["crash_guard_ok"] = crash_guard_ok
        self._diagnostics["crash_guard_reason"] = crash_guard_reason
        from PyQt6.QtWebEngineCore import QWebEngineSettings

        self._diagnostics["webengine_local_remote_urls"] = self.web_view.settings().testAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls
        )
        self._diagnostics["webengine_local_file_urls"] = self.web_view.settings().testAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls
        )
        map_path = self._map_asset_paths()["map_html"]
        if not map_path.exists():
            self._show_map_failure(
                "Live map assets are missing",
                "Rebuild the packaged app with NetTrap.spec so assets/map.html and Leaflet files are bundled.",
            )
            return

        self._page_ready = False
        assets_root = map_path.parent
        map_url = QUrl.fromLocalFile(str(map_path))
        self._diagnostics["map_load_strategy"] = "file_url_fallback"
        force_file_url = os.environ.get("NETTRAP_MAP_FORCE_FILE_URL", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if force_file_url:
            self._diagnostics["map_load_strategy"] = "file_url_forced"
        else:
            try:
                base_url = self._start_asset_server(assets_root)
                self._diagnostics["asset_server_base_url"] = base_url
                self._diagnostics["map_load_strategy"] = "loopback_http"
                map_url = QUrl(f"{base_url}/map.html")
            except Exception as exc:
                self._diagnostics["asset_server_error"] = str(exc)

        self._diagnostics["last_url"] = map_url.toString()
        self._load_timeout.start()
        try:
            self.web_view.load(map_url)
        except Exception as exc:
            self._diagnostics["browser_init_error"] = str(exc)
            self._show_map_failure(
                "Live map browser failed to load assets",
                f"QWebEngineView.load() raised an exception: {exc}",
            )

    def _dismiss_banner(self):
        self._banner_visible = False
        self.banner.hide()

    def _on_load_started(self):
        self._diagnostics["load_started"] = True

    def _on_load_finished(self, ok: bool):
        self._load_timeout.stop()
        self._diagnostics["load_finished"] = bool(ok)
        self._page_ready = ok
        self._position_overlays()
        if not ok:
            self._show_map_failure(
                "Live map failed to load",
                "QWebEngine reported loadFinished(False) while opening the embedded map.",
            )
            return

        self._probe_loaded_page()

    def _probe_loaded_page(self) -> None:
        if self.web_view is None:
            return

        self._page_probe_timeout.start()
        self.web_view.page().runJavaScript(
            """
            (() => JSON.stringify({
                href: window.location.href,
                hasMapElement: !!document.getElementById("map"),
                leafletAvailable: typeof window.L !== "undefined",
                mapApiAvailable: typeof window.addMarker === "function" && typeof window.clearMarkers === "function",
                stylesheets: Array.from(document.querySelectorAll('link[rel="stylesheet"]')).map((node) => node.href),
                scripts: Array.from(document.scripts).map((node) => node.src || "[inline]")
            }))();
            """,
            self._on_page_probe_complete,
        )

    def _on_page_probe_complete(self, payload) -> None:
        if self.web_view is None or not self._interactive_map_available:
            return

        self._page_probe_timeout.stop()
        self._diagnostics["page_probe_completed"] = True

        data: dict[str, object] = {}
        if isinstance(payload, str) and payload:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"raw": payload}
        elif isinstance(payload, dict):
            data = payload

        if isinstance(data.get("href"), str):
            self._diagnostics["last_url"] = data["href"]

        leaflet_available = bool(data.get("leafletAvailable"))
        map_api_available = bool(data.get("mapApiAvailable"))
        local_source = self._diagnostics.get("map_load_strategy") == "file_url_fallback"
        self._diagnostics["leaflet_available"] = leaflet_available
        self._diagnostics["map_api_available"] = map_api_available
        self._diagnostics["local_file_access_blocked"] = (
            local_source
            and
            bool(self._diagnostics["map_js_exists"])
            and bool(self._diagnostics["leaflet_js_exists"])
            and not (leaflet_available and map_api_available)
        )
        self._diagnostics["js_probe_summary"] = json.dumps(data, sort_keys=True)

        if not leaflet_available or not map_api_available:
            self._page_ready = False
            self._show_map_failure(
                "Live map assets did not initialize",
                "The HTML page opened, but the embedded Leaflet scripts did not initialize correctly.",
            )
            return

        self._page_ready = True
        self.refresh_map()

    @staticmethod
    def _append_limited(target: list, item, limit: int = 40) -> None:
        target.append(item)
        if len(target) > limit:
            del target[: len(target) - limit]

    def _on_request_observed(self, payload: dict) -> None:
        url = str(payload.get("url", ""))
        if not any(
            host in url
            for host in (
                "tile.openstreetmap.org",
                ".basemaps.cartocdn.com",
                "127.0.0.1",
            )
        ):
            return

        self._diagnostics["tile_request_count"] = int(self._diagnostics["tile_request_count"]) + 1
        urls = self._diagnostics["tile_request_urls"]
        if isinstance(urls, list):
            self._append_limited(urls, url, limit=30)

    def _on_console_message(self, payload: dict) -> None:
        level = str(payload.get("level", ""))
        if level.lower() not in {"error", "warning"}:
            return
        messages = self._diagnostics["js_console_errors"]
        if isinstance(messages, list):
            self._append_limited(messages, payload, limit=30)

    def _on_certificate_error(self, payload: dict) -> None:
        errors = self._diagnostics["certificate_errors"]
        if isinstance(errors, list):
            self._append_limited(errors, payload, limit=20)

    def _on_url_changed(self, url: QUrl) -> None:
        self._diagnostics["last_url"] = url.toString()

    def _on_load_timeout(self) -> None:
        self._diagnostics["load_timeout"] = True
        reason = (
            "QWebEngine did not emit loadStarted() for the embedded map."
            if not self._diagnostics["load_started"]
            else "QWebEngine started loading the embedded map but did not finish in time."
        )
        self._show_map_failure("Live map timed out", reason)

    def _on_page_probe_timeout(self) -> None:
        self._diagnostics["page_probe_timeout"] = True
        self._page_ready = False
        self._show_map_failure(
            "Live map JavaScript timed out",
            "The HTML page opened, but the embedded map scripts did not become ready in time.",
        )

    def _on_render_process_terminated(self, termination_status, exit_code):
        self._diagnostics["render_process_terminated"] = True
        self._diagnostics["render_termination_status"] = getattr(termination_status, "name", str(termination_status))
        self._diagnostics["render_exit_code"] = exit_code
        self._show_map_failure(
            "Live map browser crashed",
            "QWebEngine terminated while rendering the map, so NetTrap disabled the embedded map instead of crashing the app.",
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlays()

    def _position_overlays(self):
        if self.banner.parent() is self.map_shell:
            width = min(max(self.map_shell.width() - 48, 320), 760)
            x = max(24, (self.map_shell.width() - width) // 2)
            self.banner.setGeometry(x, 24, width, self.banner.sizeHint().height() + 12)
            self.empty_state.setGeometry(0, 0, self.map_shell.width(), self.map_shell.height())

    def refresh_map(self):
        if not self._page_ready:
            return

        rows = self.db._fetch_rows(
            """
            SELECT source_ip, country, city, latitude, longitude,
                   COUNT(*) AS sessions, MAX(started_at) AS last_seen
            FROM sessions
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            GROUP BY source_ip, country, city, latitude, longitude
            ORDER BY sessions DESC, last_seen DESC
            """
        )

        if not rows:
            self._run_js("clearMarkers();")
            self._last_marker_ips.clear()
            self.empty_state.setVisible(self._interactive_map_available)
            return

        current_marker_ips = {str(row["source_ip"]) for row in rows}
        for row in rows:
            self._run_js(
                "addMarker(%r, %s, %s, %r, %r, %d, %r);"
                % (
                    row["source_ip"],
                    row["latitude"],
                    row["longitude"],
                    row.get("country") or "",
                    row.get("city") or "",
                    int(row["sessions"]),
                    self._time_only(row.get("last_seen")),
                )
            )
        if current_marker_ips != self._last_marker_ips:
            self._run_js("fitBounds();")
            self._last_marker_ips = current_marker_ips
        self.empty_state.setVisible(False)

    def set_active(self, active: bool):
        if active:
            self._initialize_map()
            if not self.refresh_timer.isActive():
                self.refresh_timer.start()
            self.refresh_map()
        else:
            self.refresh_timer.stop()

    def on_new_event(self, event: dict):
        source_ip = event.get("source_ip")
        if not source_ip or not self._page_ready:
            return

        rows = self.db._fetch_rows(
            """
            SELECT source_ip
            FROM sessions
            WHERE source_ip = ? AND latitude IS NOT NULL AND longitude IS NOT NULL
            LIMIT 1
            """,
            (source_ip,),
        )
        if not rows:
            return
        self._run_js(f"pulseMarker({source_ip!r});")

    def _run_js(self, script: str):
        if self.web_view is None:
            return
        self.web_view.page().runJavaScript(script)

    @staticmethod
    def _time_only(timestamp: str | None) -> str:
        return format_local_time(timestamp)

    def diagnostics_snapshot(self) -> dict[str, object]:
        try:
            return json.loads(json.dumps(self._diagnostics))
        except Exception:
            return dict(self._diagnostics)

    def closeEvent(self, event):
        try:
            self._load_timeout.stop()
            self._page_probe_timeout.stop()
            self._stop_asset_server()
            self.refresh_timer.stop()
            self.geoip.close()
            self.db.close()
        finally:
            super().closeEvent(event)
