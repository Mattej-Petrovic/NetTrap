from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

try:
    import geoip2.database
    import geoip2.errors
except Exception:  # pragma: no cover - dependency guard
    geoip2 = None


class GeoIPLookup:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._reader = None
        self._available = False
        self._cache: dict[str, dict[str, Any]] = {}

        if not self.db_path.exists() or geoip2 is None:
            return

        try:
            self._reader = geoip2.database.Reader(str(self.db_path))
        except Exception:
            self._reader = None
            self._available = False
        else:
            self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def lookup(self, ip: str) -> dict:
        if ip in self._cache:
            return dict(self._cache[ip])

        if not self._available or self._reader is None:
            self._cache[ip] = {}
            return {}

        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            self._cache[ip] = {}
            return {}

        if address.is_private or address.is_loopback or address.is_link_local:
            self._cache[ip] = {}
            return {}

        try:
            result = self._reader.city(ip)
        except (geoip2.errors.AddressNotFoundError, ValueError):
            self._cache[ip] = {}
            return {}
        except Exception:
            self._cache[ip] = {}
            return {}

        payload = {
            "country": result.country.name,
            "country_code": result.country.iso_code,
            "city": result.city.name,
            "latitude": result.location.latitude,
            "longitude": result.location.longitude,
        }
        cleaned = {key: value for key, value in payload.items() if value is not None}
        self._cache[ip] = cleaned
        return dict(cleaned)

    def close(self):
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        self._available = False
