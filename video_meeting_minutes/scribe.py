from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from elevenlabs.client import ElevenLabs

from .models import TranscriptSegment
from .timefmt import format_time


def to_plain_data(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return result
    raise TypeError(f"Unsupported ElevenLabs response type: {type(result)!r}")


def transcribe_with_scribe(
    audio_path: Path,
    *,
    api_key: str,
    model_id: str = "scribe_v2",
    language_code: str = "ja",
    diarize: bool = False,
    keyterms: list[str] | None = None,
    no_verbatim: bool = False,
) -> dict[str, Any]:
    client = ElevenLabs(api_key=api_key)
    request: dict[str, Any] = {
        "model_id": model_id,
        "language_code": language_code,
        "timestamps_granularity": "word",
        "diarize": diarize,
        "no_verbatim": no_verbatim,
        "tag_audio_events": False,
    }
    if keyterms:
        request["keyterms"] = keyterms

    with audio_path.open("rb") as audio_file:
        return to_plain_data(client.speech_to_text.convert(file=audio_file, **request))


def transcript_segments(
    transcript: dict[str, Any],
    *,
    max_chars: int = 240,
    pause_break_seconds: float = 1.4,
) -> list[TranscriptSegment]:
    words = transcript.get("words") or []
    segments: list[TranscriptSegment] = []
    current_text = ""
    current_start: float | None = None
    current_end: float | None = None
    current_speaker: str | None = None

    def flush() -> None:
        nonlocal current_text, current_start, current_end, current_speaker
        text = current_text.strip()
        if text:
            segments.append(
                TranscriptSegment(
                    start=current_start or 0,
                    end=current_end or current_start or 0,
                    speaker=current_speaker,
                    text=text,
                )
            )
        current_text = ""
        current_start = None
        current_end = None
        current_speaker = None

    for word in words:
        text = str(word.get("text") or "")
        if not text:
            continue
        kind = word.get("type")
        speaker = word.get("speaker_id")
        start = word.get("start")
        end = word.get("end")

        if kind == "spacing":
            current_text += text
            continue
        if kind == "audio_event":
            flush()
            continue

        start_f = float(start) if start is not None else None
        end_f = float(end) if end is not None else start_f
        if current_start is None:
            current_start = start_f or 0
            current_speaker = speaker

        should_break = False
        if current_end is not None and start_f is not None:
            should_break = start_f - current_end > pause_break_seconds
        if speaker != current_speaker:
            should_break = True
        if len(current_text) >= max_chars:
            should_break = True

        if should_break:
            flush()
            current_start = start_f or 0
            current_speaker = speaker

        current_text += text
        current_end = end_f

        if text.rstrip().endswith(("。", "?", "？", "!", "！")):
            flush()

    flush()
    if not segments and transcript.get("text"):
        segments.append(TranscriptSegment(start=0, end=0, text=str(transcript["text"])))
    return segments


def write_transcript_outputs(
    transcript: dict[str, Any],
    segments: list[TranscriptSegment],
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "elevenlabs_scribe_v2.json"
    txt_path = output_dir / "elevenlabs_scribe_v2.txt"

    json_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"language_code: {transcript.get('language_code', '')}",
        f"duration: {format_time(transcript.get('audio_duration_secs', 0))}",
        "",
        "text:",
        str(transcript.get("text", "")).strip(),
        "",
        "segments:",
    ]
    for segment in segments:
        speaker = f" {segment.speaker}:" if segment.speaker else ""
        lines.append(
            f"[{format_time(segment.start)} - {format_time(segment.end)}]{speaker} {segment.text}"
        )

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return txt_path, json_path
