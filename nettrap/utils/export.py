from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc


def export_to_json(sessions: list, events: list, filepath: str):
    event_map: dict[str, list] = {}
    for event in events:
        event_map.setdefault(event.get("session_id"), []).append(event)

    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "total_sessions": len(sessions),
        "total_events": len(events),
        "sessions": [],
    }

    for session in sessions:
        row = dict(session)
        row["events"] = event_map.get(session.get("id"), [])
        payload["sessions"].append(row)

    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def export_to_csv(sessions: list, events: list, filepath: str):
    base_path = Path(filepath)
    base_path.parent.mkdir(parents=True, exist_ok=True)

    session_columns = [
        "id",
        "service",
        "source_ip",
        "source_port",
        "country",
        "country_code",
        "city",
        "latitude",
        "longitude",
        "started_at",
        "ended_at",
        "duration_sec",
    ]
    event_columns = [
        "id",
        "session_id",
        "timestamp",
        "event_type",
        "data",
        "service",
        "source_ip",
        "source_port",
    ]

    sessions_path = base_path.with_name(f"{base_path.name}_sessions.csv")
    with sessions_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=session_columns)
        writer.writeheader()
        for session in sessions:
            writer.writerow({column: session.get(column) for column in session_columns})

    events_path = base_path.with_name(f"{base_path.name}_events.csv")
    with events_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=event_columns)
        writer.writeheader()
        for event in events:
            row = {column: event.get(column) for column in event_columns}
            if isinstance(row.get("data"), dict):
                row["data"] = json.dumps(row["data"], ensure_ascii=False)
            writer.writerow(row)
