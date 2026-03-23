from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    service TEXT NOT NULL,
    source_ip TEXT NOT NULL,
    source_port INTEGER NOT NULL,
    country TEXT,
    country_code TEXT,
    city TEXT,
    latitude REAL,
    longitude REAL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_sec REAL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    data TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    event_id INTEGER,
    timestamp TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'low',
    message TEXT NOT NULL,
    data TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (event_id) REFERENCES events(id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_source_ip ON sessions(source_ip);
CREATE INDEX IF NOT EXISTS idx_sessions_service ON sessions(service);
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path))
        self._write_lock = threading.Lock()
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_file), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._write_lock:
            self.conn.executescript(SCHEMA_SQL)
            self._ensure_session_columns()
            self.conn.commit()

    def _ensure_session_columns(self) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "country_code" not in columns:
            self.conn.execute("ALTER TABLE sessions ADD COLUMN country_code TEXT")

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat()

    def _fetch_rows(self, query: str, params: tuple = ()) -> list[dict]:
        cursor = self.conn.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def insert_session(self, session):
        payload = session.to_dict() if hasattr(session, "to_dict") else dict(session)
        with self._write_lock:
            self.conn.execute(
                """
                INSERT INTO sessions (
                    id, service, source_ip, source_port, country, country_code, city,
                    latitude, longitude, started_at, ended_at, duration_sec
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["service"],
                    payload["source_ip"],
                    payload["source_port"],
                    payload.get("country"),
                    payload.get("country_code"),
                    payload.get("city"),
                    payload.get("latitude"),
                    payload.get("longitude"),
                    payload["started_at"],
                    payload.get("ended_at"),
                    payload.get("duration_sec"),
                ),
            )
            self.conn.commit()

    def update_session_end(self, session_id, ended_at, duration_sec):
        with self._write_lock:
            self.conn.execute(
                """
                UPDATE sessions
                SET ended_at = ?, duration_sec = ?
                WHERE id = ?
                """,
                (ended_at, duration_sec, session_id),
            )
            self.conn.commit()

    def insert_event(self, session_id, event_type, data: dict):
        with self._write_lock:
            cursor = self.conn.execute(
                """
                INSERT INTO events (session_id, timestamp, event_type, data)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, self._now_iso(), event_type, json.dumps(data)),
            )
            self.conn.commit()
            return cursor.lastrowid

    def insert_alert(self, session_id, event_id, alert_type, severity, message, data: dict):
        with self._write_lock:
            cursor = self.conn.execute(
                """
                INSERT INTO alerts (
                    session_id, event_id, timestamp, alert_type, severity, message, data
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    event_id,
                    self._now_iso(),
                    alert_type,
                    severity,
                    message,
                    json.dumps(data),
                ),
            )
            self.conn.commit()
            return cursor.lastrowid

    def get_sessions(self, limit=100, offset=0, service=None, search=None, after=None, before=None):
        query = """
            SELECT s.*
            FROM sessions AS s
        """
        params: list = []
        conditions: list[str] = []

        if service:
            conditions.append("s.service = ?")
            params.append(service)

        if search:
            conditions.append(
                """
                (
                    s.source_ip LIKE ?
                    OR EXISTS (
                        SELECT 1
                        FROM events AS e
                        WHERE e.session_id = s.id
                        AND lower(e.data) LIKE lower(?)
                    )
                )
                """
            )
            like_search = f"%{search}%"
            params.extend([like_search, like_search])

        if after:
            conditions.append("s.started_at >= ?")
            params.append(after)

        if before:
            conditions.append("s.started_at <= ?")
            params.append(before)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY s.started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return self._fetch_rows(query, tuple(params))

    def get_session_events(self, session_id):
        rows = self._fetch_rows(
            """
            SELECT id, session_id, timestamp, event_type, data
            FROM events
            WHERE session_id = ?
            ORDER BY timestamp ASC, id ASC
            """,
            (session_id,),
        )
        for row in rows:
            row["data"] = json.loads(row["data"])
        return rows

    def get_active_sessions_count(self):
        row = self.conn.execute(
            "SELECT COUNT(*) AS total FROM sessions WHERE ended_at IS NULL"
        ).fetchone()
        return row["total"]

    def get_connections_per_hour(self, hours=24):
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        return self._fetch_rows(
            """
            SELECT
                strftime('%Y-%m-%dT%H:00:00', started_at) || '+00:00' AS hour,
                COUNT(*) AS count
            FROM sessions
            WHERE started_at >= ?
            GROUP BY hour
            ORDER BY hour ASC
            """,
            (cutoff,),
        )

    def get_unique_ips_count(self, hours=24):
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        row = self.conn.execute(
            """
            SELECT COUNT(DISTINCT source_ip) AS total
            FROM sessions
            WHERE started_at >= ?
            """,
            (cutoff,),
        ).fetchone()
        return row["total"]

    def get_top_credentials(self, limit=10, after=None, before=None):
        query = """
            SELECT e.data
            FROM events AS e
            JOIN sessions AS s ON s.id = e.session_id
            WHERE e.event_type = 'auth_attempt'
        """
        params: list = []
        if after:
            query += " AND e.timestamp >= ?"
            params.append(after)
        if before:
            query += " AND e.timestamp <= ?"
            params.append(before)
        rows = self._fetch_rows(query, tuple(params))
        counts: dict[str, int] = {}
        for row in rows:
            payload = json.loads(row["data"])
            username = payload.get("username")
            password = payload.get("password")
            if username is None and password is None:
                continue
            key = f"{username}:{password}"
            counts[key] = counts.get(key, 0) + 1

        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [{"credential": credential, "count": count} for credential, count in ranked[:limit]]

    def get_top_user_agents(self, limit=10, after=None, before=None):
        query = """
            SELECT e.data
            FROM events AS e
            JOIN sessions AS s ON s.id = e.session_id
            WHERE e.event_type = 'http_request'
        """
        params: list = []
        if after:
            query += " AND e.timestamp >= ?"
            params.append(after)
        if before:
            query += " AND e.timestamp <= ?"
            params.append(before)
        rows = self._fetch_rows(query, tuple(params))
        counts: dict[str, int] = {}
        for row in rows:
            payload = json.loads(row["data"])
            user_agent = payload.get("user_agent")
            if not user_agent:
                continue
            counts[user_agent] = counts.get(user_agent, 0) + 1

        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [{"user_agent": user_agent, "count": count} for user_agent, count in ranked[:limit]]

    def get_top_attacking_ips(self, limit=10, after=None, before=None):
        query = """
            SELECT source_ip, COUNT(*) AS count
            FROM sessions
        """
        params: list = []
        conditions: list[str] = []
        if after:
            conditions.append("started_at >= ?")
            params.append(after)
        if before:
            conditions.append("started_at <= ?")
            params.append(before)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += """
            GROUP BY source_ip
            ORDER BY count DESC, source_ip ASC
            LIMIT ?
        """
        params.append(limit)
        return self._fetch_rows(query, tuple(params))

    def get_service_distribution(self, after=None, before=None):
        query = """
            SELECT service, COUNT(*) AS count
            FROM sessions
        """
        params: list = []
        conditions: list[str] = []
        if after:
            conditions.append("started_at >= ?")
            params.append(after)
        if before:
            conditions.append("started_at <= ?")
            params.append(before)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += """
            GROUP BY service
            ORDER BY count DESC, service ASC
        """
        return self._fetch_rows(query, tuple(params))

    def get_alerts_count(self):
        row = self.conn.execute("SELECT COUNT(*) AS total FROM alerts").fetchone()
        return row["total"]

    def get_total_events_count(self, service=None, after=None, before=None):
        query = """
            SELECT COUNT(*) AS total
            FROM events AS e
            JOIN sessions AS s ON s.id = e.session_id
        """
        params: list = []
        conditions: list[str] = []

        if service:
            conditions.append("s.service = ?")
            params.append(service)
        if after:
            conditions.append("e.timestamp >= ?")
            params.append(after)
        if before:
            conditions.append("e.timestamp <= ?")
            params.append(before)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        row = self.conn.execute(query, tuple(params)).fetchone()
        return row["total"]

    def get_total_sessions_count(self, service=None, after=None, before=None):
        query = "SELECT COUNT(*) AS total FROM sessions"
        params: list = []
        conditions: list[str] = []

        if service:
            conditions.append("service = ?")
            params.append(service)
        if after:
            conditions.append("started_at >= ?")
            params.append(after)
        if before:
            conditions.append("started_at <= ?")
            params.append(before)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        row = self.conn.execute(query, tuple(params)).fetchone()
        return row["total"]

    def export_sessions(self, service=None, after=None, before=None):
        query = "SELECT * FROM sessions"
        params: list = []
        conditions: list[str] = []

        if service:
            conditions.append("service = ?")
            params.append(service)
        if after:
            conditions.append("started_at >= ?")
            params.append(after)
        if before:
            conditions.append("started_at <= ?")
            params.append(before)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY started_at DESC"
        return self._fetch_rows(query, tuple(params))

    def export_events(self, service=None, after=None, before=None):
        query = """
            SELECT
                e.id,
                e.session_id,
                e.timestamp,
                e.event_type,
                e.data,
                s.service,
                s.source_ip,
                s.source_port
            FROM events AS e
            JOIN sessions AS s ON s.id = e.session_id
        """
        params: list = []
        conditions: list[str] = []

        if service:
            conditions.append("s.service = ?")
            params.append(service)
        if after:
            conditions.append("e.timestamp >= ?")
            params.append(after)
        if before:
            conditions.append("e.timestamp <= ?")
            params.append(before)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY e.timestamp DESC, e.id DESC"
        rows = self._fetch_rows(query, tuple(params))
        for row in rows:
            row["data"] = json.loads(row["data"])
        return rows

    def close(self):
        with self._write_lock:
            self.conn.close()

    def reset_schema(self):
        with self._write_lock:
            self.conn.executescript(
                """
                DROP TABLE IF EXISTS alerts;
                DROP TABLE IF EXISTS events;
                DROP TABLE IF EXISTS sessions;
                """
            )
            self.conn.executescript(SCHEMA_SQL)
            self.conn.commit()
