"""Bounded event history and inclusive reconnect cursor for Docker events."""

import json
from collections import deque
from typing import Optional


class EventFeed:
    def __init__(self, max_events: int = 100):
        self.rows: deque[dict] = deque(maxlen=max(1, max_events))
        self.cursor = 0
        self.status = "connecting"
        self.deleted = False

    @property
    def since(self) -> Optional[str]:
        if not self.cursor:
            return None
        seconds, nanoseconds = divmod(self.cursor, 1_000_000_000)
        return f"{seconds}.{nanoseconds:09d}"

    def append(self, line: str) -> bool:
        try:
            row = json.loads(line)
            stamp = int(row.get("timeNano") or int(row.get("time", 0)) * 1_000_000_000)
            actor = row.get("Actor") or {}
            key = (stamp, actor.get("ID", ""), row.get("Action", row.get("status", "")))
        except (ValueError, TypeError, AttributeError):
            return False
        if not key[2] or any(item["_key"] == key for item in self.rows):
            return False
        row["_key"] = key
        self.rows.append(row)
        self.cursor = max(self.cursor, stamp)
        self.deleted = key[2] == "destroy"
        self.status = "container removed" if self.deleted else "connected"
        return True

    def disconnect(self, returncode: int) -> None:
        self.status = f"disconnected (exit {returncode}); reconnecting"

    def lines(self) -> list[str]:
        lines = [f"Events: {self.status} [E] toggle"]
        for row in self.rows:
            stamp, identifier, action = row["_key"]
            attributes = (row.get("Actor") or {}).get("Attributes") or {}
            detail = " ".join(
                f"{key}={str(attributes[key])[:256]}"
                for key in ("name", "exitCode", "signal")
                if key in attributes
            )
            lines.append(f"{stamp // 1_000_000_000} {identifier[:12]} {action} {detail}")
        return lines
