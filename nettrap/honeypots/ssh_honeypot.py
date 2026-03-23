from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import paramiko

from nettrap.honeypots.base import BaseHoneypot
from nettrap.utils.ip_utils import resolve_bind_host


class _SSHServer(paramiko.ServerInterface):
    def __init__(self, honeypot: "SSHHoneypot", session):
        self.honeypot = honeypot
        self.session = session
        self.auth_attempts = 0
        self.disconnect_requested = threading.Event()

    def check_auth_password(self, username, password):
        self.auth_attempts += 1
        self.honeypot.log_event(
            self.session.id,
            "auth_attempt",
            {"username": username, "password": password},
        )
        if self.auth_attempts >= self.honeypot.max_auth_attempts:
            self.disconnect_requested.set()
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def get_allowed_auths(self, username):
        return "password"


class SSHHoneypot(BaseHoneypot):
    def __init__(self, host, port, db, logger, banner, event_queue=None, geoip=None):
        super().__init__("ssh", port, db, logger, event_queue, geoip=geoip)
        self.host = resolve_bind_host(host)
        self.banner = banner
        self.max_auth_attempts = 6
        self._stop_event = threading.Event()
        self._server_socket = None
        self._host_key = self._load_or_create_host_key()

    def _host_key_path(self) -> Path:
        db_path = Path(self.db.db_path)
        return db_path.parent / "ssh_host_key"

    def _load_or_create_host_key(self):
        path = self._host_key_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return paramiko.RSAKey.from_private_key_file(str(path))

        key = paramiko.RSAKey.generate(2048)
        key.write_private_key_file(str(path))
        try:
            path.chmod(0o600)
        except Exception:
            pass
        return key

    def _handle_client(self, client, addr):
        session = None
        transport = None
        try:
            client.settimeout(30)
            session = self.create_session(addr[0], addr[1])
            transport = paramiko.Transport(client)
            transport.local_version = self.banner
            transport.banner_timeout = 30
            transport.auth_timeout = 30
            transport.add_server_key(self._host_key)
            server = _SSHServer(self, session)
            transport.start_server(server=server)

            start = time.monotonic()
            while transport.is_active() and not self._stop_event.is_set():
                if server.disconnect_requested.is_set():
                    break
                if time.monotonic() - start > 30:
                    break
                time.sleep(0.2)
        except Exception:
            pass
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass
            if session is not None:
                try:
                    self.end_session(session)
                except Exception:
                    pass
            try:
                client.close()
            except Exception:
                pass

    def start(self):
        self._stop_event.clear()
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket = server_socket
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen(100)
        server_socket.settimeout(1.0)

        try:
            while not self._stop_event.is_set():
                try:
                    client, addr = server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                thread = threading.Thread(
                    target=self._handle_client,
                    args=(client, addr),
                    daemon=True,
                )
                thread.start()
        finally:
            self.stop()

    def stop(self):
        self._stop_event.set()
        server_socket = self._server_socket
        self._server_socket = None
        if server_socket is not None:
            try:
                server_socket.close()
            except Exception:
                pass
