from __future__ import annotations

from datetime import datetime
from uuid import uuid4

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc


class Session:
    """Represents a single honeypot connection session."""

    def __init__(
        self,
        service: str,
        source_ip: str,
        source_port: int,
        country=None,
        country_code=None,
        city=None,
        latitude=None,
        longitude=None,
    ):
        self.id = str(uuid4())
        self.service = service
        self.source_ip = source_ip
        self.source_port = source_port
        self.country = country
        self.country_code = country_code
        self.city = city
        self.latitude = latitude
        self.longitude = longitude
        self.started_at = datetime.now(UTC).isoformat()
        self.ended_at = None
        self.duration_sec = None

    def end(self):
        if self.ended_at is not None:
            return

        ended_at_dt = datetime.now(UTC)
        started_at_dt = datetime.fromisoformat(self.started_at)
        self.ended_at = ended_at_dt.isoformat()
        self.duration_sec = (ended_at_dt - started_at_dt).total_seconds()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service": self.service,
            "source_ip": self.source_ip,
            "source_port": self.source_port,
            "country": self.country,
            "country_code": self.country_code,
            "city": self.city,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_sec": self.duration_sec,
        }
