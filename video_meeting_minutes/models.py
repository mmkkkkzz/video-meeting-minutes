from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FrameEvent:
    index: int
    timestamp: float
    path: Path
    diff_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "path": str(self.path),
            "diff_score": self.diff_score,
        }


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "speaker": self.speaker,
            "text": self.text,
        }


@dataclass(frozen=True)
class FrameAnalysis:
    index: int
    timestamp: float
    image_path: Path
    analysis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "image_path": str(self.image_path),
            "analysis": self.analysis,
        }
