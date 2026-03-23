from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc


class JsonLogger:
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log_event(self, session_id: str, event_type: str, data: dict):
        now = datetime.now(UTC)
        timestamp = now.isoformat()
        filename = f"nettrap_{now.date().isoformat()}.jsonl"
        entry = {
            "timestamp": timestamp,
            "session_id": session_id,
            "event_type": event_type,
            "data": data,
        }

        with self._lock:
            path = self.log_dir / filename
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
