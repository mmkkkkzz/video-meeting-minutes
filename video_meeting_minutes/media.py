from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .models import FrameEvent
from .timefmt import format_time


def require_media_tools() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing:
        raise RuntimeError(f"Missing media tools: {', '.join(missing)}")


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, check=True, text=True)


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(audio_path),
        ]
    )
    return audio_path


def get_video_duration(video_path: Path) -> float:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
    )
    return float(result.stdout.strip())


def resize_for_diff(frame: np.ndarray, width: int = 480) -> np.ndarray:
    height, current_width = frame.shape[:2]
    if current_width <= width:
        resized = frame
    else:
        scale = width / current_width
        resized = cv2.resize(frame, (width, int(height * scale)))
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (7, 7), 0)


def save_frame(frame: np.ndarray, frames_dir: Path, index: int, timestamp: float) -> Path:
    filename = f"frame_{index:04d}_{format_time(timestamp).replace(':', '-')}.jpg"
    path = frames_dir / filename
    cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    return path


def detect_changed_frames(
    video_path: Path,
    frames_dir: Path,
    *,
    sample_fps: float = 1.0,
    diff_threshold: float = 18.0,
    min_gap_seconds: float = 8.0,
    max_frames: int = 80,
    include_first_frame: bool = True,
) -> list[FrameEvent]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    source_fps = capture.get(cv2.CAP_PROP_FPS) or 30
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round(source_fps / max(sample_fps, 0.01))))

    events: list[FrameEvent] = []
    previous: np.ndarray | None = None
    last_saved_ts = -10**9
    sample_index = 0
    frame_number = 0

    while frame_number < frame_count:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = capture.read()
        if not ok:
            break

        timestamp = frame_number / source_fps
        current = resize_for_diff(frame)
        diff_score = 0.0
        should_save = False

        if previous is None:
            should_save = include_first_frame
        else:
            diff_score = float(np.mean(cv2.absdiff(current, previous)))
            enough_gap = timestamp - last_saved_ts >= min_gap_seconds
            should_save = diff_score >= diff_threshold and enough_gap

        if should_save:
            event_index = len(events) + 1
            path = save_frame(frame, frames_dir, event_index, timestamp)
            events.append(
                FrameEvent(
                    index=event_index,
                    timestamp=timestamp,
                    path=path,
                    diff_score=round(diff_score, 3),
                )
            )
            last_saved_ts = timestamp
            if len(events) >= max_frames:
                break

        previous = current
        sample_index += 1
        frame_number = sample_index * step

    capture.release()
    return events
