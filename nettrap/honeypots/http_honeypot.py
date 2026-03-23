from __future__ import annotations

import asyncio
import contextlib
import html
import ipaddress
import json
import threading
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

from aiohttp import web

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc

from nettrap.honeypots.base import BaseHoneypot
from nettrap.utils.ip_utils import resolve_bind_host

LOGIN_PATHS = frozenset({"/", "/admin", "/login", "/wp-login.php"})
LOGIN_PAGE_PROFILES: dict[str, dict[str, str]] = {
    "admin": {
        "window_title": "Secure Sign-In",
        "headline": "Administrative Access",
        "subtitle": "Sign in to continue to the management interface.",
        "button_label": "Sign In",
        "hint": "Use your assigned account credentials. Sessions expire after inactivity.",
        "footer": "Authorized users only. Activity may be monitored.",
    },
    "router": {
        "window_title": "Device Login",
        "headline": "Network Control Panel",
        "subtitle": "Authentication is required to manage network services.",
        "button_label": "Sign In",
        "hint": "Remote management is enabled for this interface.",
        "footer": "Access is restricted to approved administrators.",
    },
    "internal": {
        "window_title": "Portal Login",
        "headline": "Internal Access Portal",
        "subtitle": "Use your directory credentials to access protected resources.",
        "button_label": "Continue",
        "hint": "If you cannot sign in, contact your system administrator.",
        "footer": "This service is intended for approved personnel only.",
    },
}


class HTTPHoneypot(BaseHoneypot):
    def __init__(
        self,
        host,
        port,
        db,
        logger,
        server_header,
        page_profile="admin",
        trust_proxy_headers=False,
        debug_proxy_resolution=False,
        config_path=None,
        event_queue=None,
        geoip=None,
    ):
        super().__init__("http", port, db, logger, event_queue, geoip=geoip)
        self.host = resolve_bind_host(host)
        self.server_header = server_header
        self.page_profile = page_profile
        self.trust_proxy_headers = trust_proxy_headers
        self.debug_proxy_resolution = debug_proxy_resolution
        self.config_path = config_path
        self._stop_event = threading.Event()
        self._loop = None
        self._runner = None
        self._site = None
        self._sessions: dict[str, dict[str, Any]] = {}
        self._sessions_lock = threading.Lock()

    @staticmethod
    def _candidate_reason(parsed_ip: str | None) -> tuple[bool, str]:
        if not parsed_ip:
            return False, "missing_or_invalid_ip"
        try:
            parsed = ipaddress.ip_address(parsed_ip)
        except ValueError:
            return False, "invalid_ip"
        if not parsed.is_global:
            return False, "not_public_ip"
        return True, "accepted_public_ip"

    def _get_peer_info(self, request: web.Request) -> tuple[str, int]:
        peername = None
        if request.transport is not None:
            peername = request.transport.get_extra_info("peername")
        if isinstance(peername, tuple) and len(peername) >= 2:
            return peername[0], peername[1]
        return request.remote or "0.0.0.0", 0

    @staticmethod
    def _parse_ip_candidate(value: str | None) -> str | None:
        if not value:
            return None

        candidate = value.strip().strip('"').strip("'")
        if not candidate or candidate.lower() == "unknown":
            return None

        if candidate.lower().startswith("for="):
            candidate = candidate[4:].strip().strip('"').strip("'")

        if candidate.startswith("["):
            end = candidate.find("]")
            if end != -1:
                candidate = candidate[1:end]
        elif candidate.count(":") == 1 and "." in candidate:
            host, _, maybe_port = candidate.rpartition(":")
            if host and maybe_port.isdigit():
                candidate = host

        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            return None

    @staticmethod
    def _is_public_ip(value: str | None) -> bool:
        if not value:
            return False
        try:
            return ipaddress.ip_address(value).is_global
        except ValueError:
            return False

    @staticmethod
    def _iter_forwarded_for_values(header_value: str) -> list[str]:
        candidates: list[str] = []
        for entry in header_value.split(","):
            for part in entry.split(";"):
                key, sep, value = part.strip().partition("=")
                if sep and key.lower() == "for":
                    candidates.append(value.strip())
        return candidates

    def _emit_proxy_diagnostics(self, payload: dict[str, Any]) -> None:
        if not self.debug_proxy_resolution:
            return
        try:
            path = self.logger.log_dir / "http_proxy_diagnostics.jsonl"
            entry = {"timestamp": datetime.now(UTC).isoformat(), **payload}
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _resolve_client_ip(self, request: web.Request) -> tuple[str, int, str, dict[str, Any]]:
        peer_ip, peer_port = self._get_peer_info(request)
        trace: dict[str, Any] = {
            "config_path": self.config_path,
            "trust_proxy_headers": self.trust_proxy_headers,
            "peer_ip": peer_ip,
            "peer_port": peer_port,
            "headers": {
                key: request.headers[key]
                for key in (
                    "X-Forwarded-For",
                    "Forwarded",
                    "X-Real-IP",
                    "X-Forwarded-Proto",
                    "X-Forwarded-Port",
                    "X-Forwarded-Host",
                )
                if key in request.headers
            },
            "candidates": [],
        }
        if not self.trust_proxy_headers:
            trace["resolved_ip"] = peer_ip
            trace["resolved_source"] = "peer"
            trace["resolution_reason"] = "proxy_headers_disabled"
            return peer_ip, peer_port, "peer", trace

        forwarded_for = request.headers.get("X-Forwarded-For", "")
        for candidate in forwarded_for.split(","):
            parsed_ip = self._parse_ip_candidate(candidate)
            accepted, reason = self._candidate_reason(parsed_ip)
            trace["candidates"].append(
                {
                    "header": "X-Forwarded-For",
                    "raw": candidate.strip(),
                    "parsed_ip": parsed_ip,
                    "accepted": accepted,
                    "reason": reason,
                }
            )
            if accepted:
                trace["resolved_ip"] = parsed_ip
                trace["resolved_source"] = "x_forwarded_for"
                trace["resolution_reason"] = "accepted_first_public_x_forwarded_for"
                return parsed_ip, peer_port, "x_forwarded_for", trace

        forwarded_header = request.headers.get("Forwarded", "")
        for candidate in self._iter_forwarded_for_values(forwarded_header):
            parsed_ip = self._parse_ip_candidate(candidate)
            accepted, reason = self._candidate_reason(parsed_ip)
            trace["candidates"].append(
                {
                    "header": "Forwarded",
                    "raw": candidate,
                    "parsed_ip": parsed_ip,
                    "accepted": accepted,
                    "reason": reason,
                }
            )
            if accepted:
                trace["resolved_ip"] = parsed_ip
                trace["resolved_source"] = "forwarded"
                trace["resolution_reason"] = "accepted_first_public_forwarded_for"
                return parsed_ip, peer_port, "forwarded", trace

        real_ip = self._parse_ip_candidate(request.headers.get("X-Real-IP"))
        accepted, reason = self._candidate_reason(real_ip)
        trace["candidates"].append(
            {
                "header": "X-Real-IP",
                "raw": request.headers.get("X-Real-IP"),
                "parsed_ip": real_ip,
                "accepted": accepted,
                "reason": reason,
            }
        )
        if accepted:
            trace["resolved_ip"] = real_ip
            trace["resolved_source"] = "x_real_ip"
            trace["resolution_reason"] = "accepted_public_x_real_ip"
            return real_ip, peer_port, "x_real_ip", trace

        trace["resolved_ip"] = peer_ip
        trace["resolved_source"] = "peer"
        trace["resolution_reason"] = "no_accepted_forwarded_ip"
        return peer_ip, peer_port, "peer", trace

    def _get_or_create_session(self, source_ip: str, source_port: int):
        now = datetime.now(UTC)
        with self._sessions_lock:
            entry = self._sessions.get(source_ip)
            if entry is not None and now - entry["last_seen"] <= timedelta(seconds=60):
                entry["last_seen"] = now
                return entry["session"]

            if entry is not None:
                self._close_session_locked(source_ip, entry)

            session = self.create_session(source_ip, source_port)
            self._sessions[source_ip] = {"session": session, "last_seen": now}
            return session

    def _close_session_locked(self, source_ip: str, entry: dict[str, Any]):
        session = entry.get("session")
        if session is None:
            return
        try:
            self.end_session(session)
        finally:
            self._sessions.pop(source_ip, None)

    def _cleanup_sessions(self):
        now = datetime.now(UTC)
        with self._sessions_lock:
            stale = [
                source_ip
                for source_ip, entry in self._sessions.items()
                if now - entry["last_seen"] > timedelta(seconds=60)
            ]
            for source_ip in stale:
                entry = self._sessions.get(source_ip)
                if entry is not None:
                    self._close_session_locked(source_ip, entry)

    def _record_request(
        self,
        session_id: str,
        request: web.Request,
        body_text: str | None,
        client_ip: str,
        socket_ip: str,
        ip_source: str,
        proxy_diagnostics: dict[str, Any] | None = None,
    ):
        event_data = {
            "method": request.method.upper(),
            "path": request.path,
            "user_agent": request.headers.get("User-Agent"),
            "client_ip": client_ip,
            "socket_ip": socket_ip,
            "ip_source": ip_source,
            "proxy_headers_trusted": self.trust_proxy_headers,
            "headers": {key: value for key, value in request.headers.items()},
            "body": body_text,
        }
        if proxy_diagnostics is not None:
            event_data["proxy_diagnostics"] = proxy_diagnostics
        self.log_event(
            session_id,
            "http_request",
            event_data,
        )

    def _record_login_attempt(
        self,
        session_id: str,
        request: web.Request,
        username: str,
        password: str,
    ) -> None:
        self.log_event(
            session_id,
            "auth_attempt",
            {
                "username": username,
                "password": password,
                "path": request.path,
                "user_agent": request.headers.get("User-Agent"),
                "result": "invalid",
            },
        )

    @staticmethod
    def _extract_login_attempt(body_text: str | None) -> tuple[str, str] | None:
        if not body_text:
            return None

        parsed = parse_qs(body_text, keep_blank_values=True)
        username_keys = ("username", "user", "email", "login")
        password_keys = ("password", "pass")

        username = next((parsed.get(key, [""])[0].strip() for key in username_keys if key in parsed), "")
        password = next((parsed.get(key, [""])[0] for key in password_keys if key in parsed), "")
        if not username and not password:
            return None
        return username, password

    def _login_profile(self) -> dict[str, str]:
        return LOGIN_PAGE_PROFILES.get(self.page_profile, LOGIN_PAGE_PROFILES["admin"])

    async def _handle_request(self, request: web.Request):
        socket_ip, source_port = self._get_peer_info(request)
        source_ip, source_port, ip_source, proxy_diagnostics = self._resolve_client_ip(request)
        session = self._get_or_create_session(source_ip, source_port)

        body_text = None
        if request.method.upper() == "POST":
            raw = await request.read()
            body_text = raw[: 10 * 1024].decode("utf-8", errors="replace")

        self._record_request(
            session.id,
            request,
            body_text,
            source_ip,
            socket_ip,
            ip_source,
            proxy_diagnostics if self.debug_proxy_resolution else None,
        )
        self._emit_proxy_diagnostics(
            {
                "kind": "request",
                "session_id": session.id,
                "resolved_ip": source_ip,
                "ip_source": ip_source,
                **proxy_diagnostics,
            }
        )
        login_attempt = self._extract_login_attempt(body_text)
        if request.method.upper() == "POST" and login_attempt is not None:
            self._record_login_attempt(session.id, request, *login_attempt)

        if request.method.upper() == "GET" and request.path in LOGIN_PATHS:
            response = web.Response(text=self._fake_login_page(request.path), content_type="text/html")
        elif request.method.upper() == "POST" and request.path in LOGIN_PATHS:
            username = login_attempt[0] if login_attempt is not None else ""
            response = web.Response(
                text=self._fake_login_page(
                    request.path,
                    error_message="Invalid credentials. Please try again.",
                    username=username,
                ),
                content_type="text/html",
            )
        else:
            response = web.Response(
                status=404,
                text=self._apache_404_page(request.path),
                content_type="text/html",
            )

        response.headers["Server"] = self.server_header
        return response

    def _fake_login_page(self, path: str, error_message: str = "", username: str = "") -> str:
        profile = self._login_profile()
        safe_path = html.escape(path, quote=True)
        safe_username = html.escape(username, quote=True)
        safe_error = html.escape(error_message)
        error_html = (
            f'<div class="alert" role="alert">{safe_error}</div>'
            if safe_error
            else ""
        )
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{window_title}</title>
    <style>
        :root {{
            color-scheme: light;
            --bg: #eef1f7;
            --card: #ffffff;
            --border: #d6dde8;
            --text: #18212f;
            --muted: #5d6b7f;
            --accent: #1554b3;
            --accent-dark: #123f84;
            --danger-bg: #fff2f2;
            --danger-border: #e9c0c0;
            --danger-text: #922727;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            min-height: 100vh;
            font-family: "Segoe UI", "Tahoma", "Arial", sans-serif;
            background:
                radial-gradient(circle at 20% 0%, rgba(21, 84, 179, 0.16), transparent 38%),
                linear-gradient(180deg, #f8fafd 0%, var(--bg) 100%);
            color: var(--text);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }}
        .shell {{
            width: 100%;
            max-width: 420px;
        }}
        .card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
            padding: 26px;
        }}
        .portal-tag {{
            display: inline-block;
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.07em;
            text-transform: uppercase;
            color: var(--muted);
        }}
        h1 {{
            margin: 16px 0 8px;
            font-size: 27px;
            line-height: 1.1;
        }}
        .subtitle {{
            margin: 0 0 18px;
            color: var(--muted);
            font-size: 14px;
            line-height: 1.5;
        }}
        .alert {{
            margin-bottom: 16px;
            padding: 12px 14px;
            border-radius: 10px;
            border: 1px solid var(--danger-border);
            background: var(--danger-bg);
            color: var(--danger-text);
            font-size: 13px;
        }}
        label {{
            display: block;
            margin: 14px 0 6px;
            font-size: 13px;
            font-weight: 600;
        }}
        input {{
            width: 100%;
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 12px 14px;
            font-size: 14px;
            background: #fbfdff;
            color: var(--text);
        }}
        input:focus {{
            outline: 2px solid rgba(31, 95, 191, 0.18);
            border-color: var(--accent);
            background: #fff;
        }}
        button {{
            width: 100%;
            margin-top: 18px;
            border: 0;
            border-radius: 10px;
            padding: 12px 14px;
            background: linear-gradient(180deg, var(--accent) 0%, var(--accent-dark) 100%);
            color: #fff;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
        }}
        button:hover {{
            filter: brightness(1.05);
        }}
        .hint {{
            margin: 14px 0 0;
            color: var(--muted);
            font-size: 12px;
            line-height: 1.5;
        }}
        .footer {{
            margin-top: 16px;
            text-align: center;
            color: var(--muted);
            font-size: 12px;
            line-height: 1.5;
        }}
    </style>
</head>
<body>
    <div class="shell">
        <div class="card">
            <div class="portal-tag">Restricted</div>
            <h1>{headline}</h1>
            <p class="subtitle">{subtitle}</p>
            {error_html}
            <form method="post" action="{path}">
                <label for="username">Username</label>
                <input id="username" name="username" type="text" value="{username}" autocomplete="username">
                <label for="password">Password</label>
                <input id="password" name="password" type="password" autocomplete="current-password">
                <button type="submit">{button_label}</button>
            </form>
            <p class="hint">{hint}</p>
        </div>
        <div class="footer">{footer}</div>
    </div>
</body>
</html>
        """.format(
            window_title=html.escape(profile["window_title"]),
            headline=html.escape(profile["headline"]),
            subtitle=html.escape(profile["subtitle"]),
            button_label=html.escape(profile["button_label"]),
            hint=html.escape(profile["hint"]),
            footer=html.escape(profile["footer"]),
            error_html=error_html,
            path=safe_path,
            username=safe_username,
        )

    def _apache_404_page(self, path: str) -> str:
        return (
            "<html><head><title>404 Not Found</title></head><body><h1>Not Found</h1>"
            f"<p>The requested URL {path} was not found on this server.</p>"
            f"<hr><address>Apache/2.4.41 (Ubuntu) Server at localhost Port {self.port}</address>"
            "</body></html>"
        )

    async def _cleanup_loop(self):
        while not self._stop_event.is_set():
            self._cleanup_sessions()
            await asyncio.sleep(5)

    async def _shutdown_async(self):
        with self._sessions_lock:
            for source_ip, entry in list(self._sessions.items()):
                self._close_session_locked(source_ip, entry)
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    async def _run_async(self):
        app = self._build_app()
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        cleanup_task = asyncio.create_task(self._cleanup_loop())
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(0.5)
        finally:
            cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await cleanup_task
            await self._shutdown_async()

    def _build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_route("*", "/", self._handle_request)
        app.router.add_route("*", "/{tail:.*}", self._handle_request)
        return app

    def start(self):
        self._stop_event.clear()
        self._emit_proxy_diagnostics(
            {
                "kind": "worker_start",
                "config_path": self.config_path,
                "host": self.host,
                "trust_proxy_headers": self.trust_proxy_headers,
                "port": self.port,
            }
        )
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_async())
        finally:
            try:
                pending = asyncio.all_tasks(loop=self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self._loop.close()
            self._loop = None

    def stop(self):
        self._stop_event.set()
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(lambda: None)
            except Exception:
                pass
