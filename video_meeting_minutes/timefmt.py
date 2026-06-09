from __future__ import annotations

from typing import Any


def format_time(seconds: Any) -> str:
    total_ms = int(round(float(seconds or 0) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"
