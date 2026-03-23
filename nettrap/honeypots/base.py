from __future__ import annotations

import json
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
        self.db.insert_event(session_id, event_type, data)
        self.logger.log_event(session_id, event_type, data)

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

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError
