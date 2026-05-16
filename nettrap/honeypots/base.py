from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc

from nettrap.core.database import Database
from nettrap.core.logger import JsonLogger
from nettrap.core.session import Session

_BRUTE_FORCE_THRESHOLD = 10       # auth attempts in a single session
_RAPID_FIRE_THRESHOLD = 5         # auth attempts within the window
_RAPID_FIRE_WINDOW_SEC = 30       # seconds for rapid_fire window
_PATH_SCAN_THRESHOLD = 15         # distinct HTTP paths in one session
_CRED_STUFFING_THRESHOLD = 3      # IPs using the same password


class BaseHoneypot:
    def __init__(
        self,
        service_name: str,
        port: int,
        db: Database,
        logger: JsonLogger,
        event_queue=None,
        geoip=None,
    ):
        self.service_name = service_name
        self.port = port
        self.db = db
        self.logger = logger
        self.event_queue = event_queue
        self.geoip = geoip

        # Per-session auth attempt count: {session_id: int}
        self._auth_counts: dict[str, int] = defaultdict(int)
        # Per-session auth timestamps for rapid-fire: {session_id: deque[float]}
        self._auth_times: dict[str, deque] = defaultdict(lambda: deque())
        # Per-session distinct paths: {session_id: set}
        self._session_paths: dict[str, set] = defaultdict(set)
        # Per-session fired alerts (avoid duplicates): {session_id: set[alert_type]}
        self._fired_alerts: dict[str, set] = defaultdict(set)
        # Password → set of IPs (cross-session credential stuffing)
        self._password_ips: dict[str, set] = defaultdict(set)
        # Track which (password, ip) pairs already triggered cred-stuffing alert
        self._cred_stuffing_alerted: set[str] = set()

    def create_session(self, source_ip: str, source_port: int) -> Session:
        geo = self.geoip.lookup(source_ip) if self.geoip else {}
        session = Session(
            service=self.service_name,
            source_ip=source_ip,
            source_port=source_port,
            country=geo.get("country"),
            country_code=geo.get("country_code"),
            city=geo.get("city"),
            latitude=geo.get("latitude"),
            longitude=geo.get("longitude"),
        )
        self.db.insert_session(session)
        return session

    def end_session(self, session: Session):
        session.end()
        self.db.update_session_end(session.id, session.ended_at, session.duration_sec)

    def _fetch_session_metadata(self, session_id: str) -> dict[str, Any]:
        with self.db._write_lock:
            row = self.db.conn.execute(
                "SELECT source_ip, service FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return {"source_ip": "unknown", "service": self.service_name}
        return {"source_ip": row["source_ip"], "service": row["service"]}

    def _build_summary(self, event_type: str, data: dict) -> str:
        if event_type == "auth_attempt":
            username = data.get("username", "")
            password = data.get("password", "")
            return f"{username}:{password}"
        if event_type == "http_request":
            method = data.get("method", "GET")
            path = data.get("path", "/")
            return f"{method} {path}"
        try:
            return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return event_type

    def log_event(self, session_id: str, event_type: str, data: dict):
        event_id = self.db.insert_event(session_id, event_type, data)
        self.logger.log_event(session_id, event_type, data)
        self._evaluate_alerts(session_id, event_id, event_type, data)

        if self.event_queue is not None:
            try:
                metadata = self._fetch_session_metadata(session_id)
                self.event_queue.put(
                    {
                        "session_id": session_id,
                        "event_type": event_type,
                        "source_ip": metadata["source_ip"],
                        "service": metadata["service"],
                        "summary": self._build_summary(event_type, data),
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
            except Exception:
                pass

    def _evaluate_alerts(self, session_id: str, event_id: int | None, event_type: str, data: dict):
        try:
            metadata = self._fetch_session_metadata(session_id)
            source_ip = metadata.get("source_ip", "unknown")
        except Exception:
            source_ip = "unknown"

        now = datetime.now(UTC).timestamp()

        if event_type == "auth_attempt":
            method = data.get("method", "password")
            password = data.get("password", "")

            # Track counts
            self._auth_counts[session_id] += 1
            count = self._auth_counts[session_id]
            times = self._auth_times[session_id]
            times.append(now)

            # Brute force: >threshold attempts in session
            if count == _BRUTE_FORCE_THRESHOLD and "brute_force" not in self._fired_alerts[session_id]:
                self._fired_alerts[session_id].add("brute_force")
                self.db.insert_alert(
                    session_id, event_id, "brute_force", "high",
                    f"Brute force: {count} auth attempts from {source_ip}",
                    {"source_ip": source_ip, "attempt_count": count},
                )

            # Rapid fire: >threshold attempts within window
            cutoff = now - _RAPID_FIRE_WINDOW_SEC
            while times and times[0] < cutoff:
                times.popleft()
            if len(times) >= _RAPID_FIRE_THRESHOLD and "rapid_fire" not in self._fired_alerts[session_id]:
                self._fired_alerts[session_id].add("rapid_fire")
                self.db.insert_alert(
                    session_id, event_id, "rapid_fire", "high",
                    f"Rapid fire: {len(times)} auth attempts in {_RAPID_FIRE_WINDOW_SEC}s from {source_ip}",
                    {"source_ip": source_ip, "attempts_in_window": len(times), "window_sec": _RAPID_FIRE_WINDOW_SEC},
                )

            # Credential stuffing: same password used from multiple IPs
            if password and method != "publickey":
                self._password_ips[password].add(source_ip)
                ip_count = len(self._password_ips[password])
                alert_key = f"cred_stuff_{password}"
                if ip_count >= _CRED_STUFFING_THRESHOLD and alert_key not in self._cred_stuffing_alerted:
                    self._cred_stuffing_alerted.add(alert_key)
                    self.db.insert_alert(
                        session_id, event_id, "credential_stuffing", "medium",
                        f"Credential stuffing: password tried from {ip_count} different IPs",
                        {"source_ip": source_ip, "distinct_ips": ip_count, "password_length": len(password)},
                    )

        elif event_type == "http_request":
            path = data.get("path", "/")
            self._session_paths[session_id].add(path)
            distinct = len(self._session_paths[session_id])
            if distinct >= _PATH_SCAN_THRESHOLD and "path_scanner" not in self._fired_alerts[session_id]:
                self._fired_alerts[session_id].add("path_scanner")
                self.db.insert_alert(
                    session_id, event_id, "path_scanner", "medium",
                    f"Path scanner: {distinct} distinct paths probed from {source_ip}",
                    {"source_ip": source_ip, "distinct_paths": distinct},
                )

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError
