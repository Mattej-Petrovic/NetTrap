from __future__ import annotations

from datetime import date, datetime, time

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc


def parse_timestamp(timestamp: str | None, *, assume_utc_for_naive: bool = True) -> datetime | None:
    if not timestamp:
        return None

    raw = str(timestamp).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None

    if parsed.tzinfo is None and assume_utc_for_naive:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def to_local_datetime(timestamp: str | None, *, assume_utc_for_naive: bool = True) -> datetime | None:
    parsed = parse_timestamp(timestamp, assume_utc_for_naive=assume_utc_for_naive)
    if parsed is None:
        return None
    return parsed.astimezone()


def format_local_time(timestamp: str | None, *, default: str = "--:--:--") -> str:
    parsed = to_local_datetime(timestamp)
    if parsed is None:
        return default
    return parsed.strftime("%H:%M:%S")


def format_local_hour(timestamp: str | None, *, default: str = "--:--") -> str:
    parsed = to_local_datetime(timestamp)
    if parsed is None:
        return default
    return parsed.strftime("%H:%M")


def local_today_start_utc_iso(now: datetime | None = None) -> str:
    now_local = now.astimezone() if now is not None else datetime.now().astimezone()
    local_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(UTC).isoformat()


def local_date_range_to_utc_iso(start_date: date, end_date: date) -> tuple[str, str]:
    start_local = datetime.combine(start_date, time.min).astimezone()
    end_local = datetime.combine(end_date, time.max).astimezone()
    return start_local.astimezone(UTC).isoformat(), end_local.astimezone(UTC).isoformat()
