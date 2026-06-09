from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .codex_app import CodexAppServerClient
from .codex_tools import analyze_frames, generate_minutes
from .media import detect_changed_frames, extract_audio, get_video_duration, require_media_tools
from .models import FrameAnalysis
from .scribe import transcribe_with_scribe, transcript_segments, write_transcript_outputs
from .timefmt import format_time


CODEX_EFFORT_CHOICES = ("none", "minimal", "low", "medium", "high", "xhigh")
DEFAULT_CODEX_MODEL = "gpt-5.5"
DEFAULT_CODEX_EFFORT = "medium"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate meeting minutes from a video using ElevenLabs Scribe v2 and visual frame analysis."
    )
    parser.add_argument("video", type=Path, help="Input video file.")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--language-code", default=None, help="ElevenLabs language code. Default: ja")
    parser.add_argument("--keyterms", nargs="*", default=[], help="Key terms for Scribe v2.")
    parser.add_argument("--keyterms-file", type=Path, default=None)
    parser.add_argument(
        "--scribe-model",
        default=None,
        help="ElevenLabs Scribe model. Default: ELEVENLABS_SCRIBE_MODEL or scribe_v2.",
    )
    diarize_group = parser.add_mutually_exclusive_group()
    diarize_group.add_argument(
        "--diarize",
        dest="diarize",
        action="store_true",
        default=True,
        help="Enable ElevenLabs diarization. Default: enabled.",
    )
    diarize_group.add_argument(
        "--no-diarize",
        dest="diarize",
        action="store_false",
        help="Disable ElevenLabs diarization.",
    )
    parser.add_argument("--no-verbatim", action="store_true")
    parser.add_argument("--sample-fps", type=float, default=1.0)
    parser.add_argument("--frame-threshold", type=float, default=18.0)
    parser.add_argument("--min-frame-gap", type=float, default=8.0)
    parser.add_argument("--max-frames", type=int, default=80)
    parser.add_argument("--codex-command", default="codex", help="Codex CLI command.")
    parser.add_argument(
        "--codex-model",
        default=None,
        help=f"Default Codex model override. Default: CODEX_MODEL or {DEFAULT_CODEX_MODEL}.",
    )
    parser.add_argument(
        "--codex-effort",
        choices=CODEX_EFFORT_CHOICES,
        default=None,
        help=f"Default Codex reasoning effort. Default: CODEX_EFFORT or {DEFAULT_CODEX_EFFORT}.",
    )
    parser.add_argument(
        "--vision-model",
        default=None,
        help="Codex model for frame image analysis. Default: CODEX_VISION_MODEL or CODEX_MODEL.",
    )
    parser.add_argument(
        "--vision-effort",
        choices=CODEX_EFFORT_CHOICES,
        default=None,
        help="Codex effort for frame image analysis. Default: CODEX_VISION_EFFORT or CODEX_EFFORT.",
    )
    parser.add_argument(
        "--minutes-model",
        default=None,
        help="Codex model for minutes generation. Default: CODEX_MINUTES_MODEL or CODEX_MODEL.",
    )
    parser.add_argument(
        "--minutes-effort",
        choices=CODEX_EFFORT_CHOICES,
        default=None,
        help="Codex effort for minutes generation. Default: CODEX_MINUTES_EFFORT or CODEX_EFFORT.",
    )
    parser.add_argument("--codex-timeout", type=float, default=600)
    parser.add_argument(
        "--codex-keep-stderr",
        action="store_true",
        help="Keep app-server stderr visible for debugging.",
    )
    parser.add_argument("--skip-vision", action="store_true", help="Skip Codex frame analysis.")
    parser.add_argument("--skip-minutes", action="store_true", help="Skip Codex minutes generation.")
    return parser.parse_args()


def read_keyterms(args: argparse.Namespace) -> list[str]:
    terms = [term.strip() for term in args.keyterms if term.strip()]
    if args.keyterms_file:
        for line in args.keyterms_file.read_text(encoding="utf-8").splitlines():
            term = line.strip()
            if term and not term.startswith("#"):
                terms.append(term)
    return sorted(set(terms))


def run_dir_for(output_dir: Path, video_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"{video_path.stem}_{timestamp}"


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is missing. Put it in .env first.")
    return value


def validate_codex_effort(name: str, value: str | None) -> str | None:
    if value and value not in CODEX_EFFORT_CHOICES:
        choices = ", ".join(CODEX_EFFORT_CHOICES)
        raise RuntimeError(f"{name} must be one of: {choices}")
    return value


def normalize_codex_model(value: str | None) -> str | None:
    if value == "gpt5.5":
        return "gpt-5.5"
    return value


def write_manifest(run_dir: Path, manifest: dict[str, object]) -> None:
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_basic_minutes(
    run_dir: Path,
    video_name: str,
    transcript_text_path: Path,
    analyses: list[FrameAnalysis],
) -> Path:
    minutes_path = run_dir / "minutes.md"
    lines = [
        f"# {video_name} 議事録ドラフト",
        "",
        "Codex app-server による議事録生成はスキップされました。",
        "",
        "## 参照ファイル",
        f"- 文字起こし: `{transcript_text_path}`",
        "",
        "## 画面変化",
    ]
    if analyses:
        for analysis in analyses:
            lines.append(f"- {format_time(analysis.timestamp)}: {analysis.analysis}")
    else:
        lines.append("- 画像解析なし")
    minutes_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return minutes_path


def main() -> int:
    load_dotenv()
    args = parse_args()
    video_path = args.video.expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    require_media_tools()
    elevenlabs_api_key = require_env("ELEVENLABS_API_KEY")

    language_code = args.language_code or os.getenv("ELEVENLABS_LANGUAGE_CODE") or "ja"
    scribe_model = args.scribe_model or os.getenv("ELEVENLABS_SCRIBE_MODEL") or "scribe_v2"
    codex_model = normalize_codex_model(args.codex_model or os.getenv("CODEX_MODEL") or DEFAULT_CODEX_MODEL)
    codex_effort = validate_codex_effort(
        "CODEX_EFFORT",
        args.codex_effort or os.getenv("CODEX_EFFORT") or DEFAULT_CODEX_EFFORT,
    )
    vision_model = normalize_codex_model(args.vision_model or os.getenv("CODEX_VISION_MODEL") or codex_model)
    minutes_model = normalize_codex_model(args.minutes_model or os.getenv("CODEX_MINUTES_MODEL") or codex_model)
    vision_effort = validate_codex_effort(
        "CODEX_VISION_EFFORT",
        args.vision_effort or os.getenv("CODEX_VISION_EFFORT") or codex_effort,
    )
    minutes_effort = validate_codex_effort(
        "CODEX_MINUTES_EFFORT",
        args.minutes_effort or os.getenv("CODEX_MINUTES_EFFORT") or codex_effort,
    )
    keyterms = read_keyterms(args)

    run_dir = run_dir_for(args.output_dir, video_path)
    audio_path = run_dir / "audio" / f"{video_path.stem}.m4a"
    frames_dir = run_dir / "frames"
    transcript_dir = run_dir / "transcript"
    vision_dir = run_dir / "vision"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Run directory: {run_dir}", flush=True)
    duration = get_video_duration(video_path)
    print(f"Video duration: {format_time(duration)}", flush=True)

    print("Extracting audio...", flush=True)
    extract_audio(video_path, audio_path)

    print("Detecting changed frames...", flush=True)
    frames = detect_changed_frames(
        video_path,
        frames_dir,
        sample_fps=args.sample_fps,
        diff_threshold=args.frame_threshold,
        min_gap_seconds=args.min_frame_gap,
        max_frames=args.max_frames,
    )
    (vision_dir / "frames.json").parent.mkdir(parents=True, exist_ok=True)
    (vision_dir / "frames.json").write_text(
        json.dumps([frame.to_dict() for frame in frames], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved {len(frames)} changed frames.", flush=True)

    diarize_label = "with diarization" if args.diarize else "without diarization"
    print(f"Transcribing with ElevenLabs {scribe_model} {diarize_label}...", flush=True)
    transcript = transcribe_with_scribe(
        audio_path,
        api_key=elevenlabs_api_key,
        model_id=scribe_model,
        language_code=language_code,
        diarize=args.diarize,
        keyterms=keyterms,
        no_verbatim=args.no_verbatim,
    )
    segments = transcript_segments(transcript)
    transcript_text_path, transcript_json_path = write_transcript_outputs(
        transcript,
        segments,
        transcript_dir,
    )
    print(f"Saved transcript: {transcript_text_path}", flush=True)

    analyses: list[FrameAnalysis] = []
    if args.skip_vision and args.skip_minutes:
        minutes_path = write_basic_minutes(run_dir, video_path.name, transcript_text_path, analyses)
    else:
        with CodexAppServerClient(
            cwd=Path.cwd(),
            command=args.codex_command,
            model=codex_model,
            timeout_seconds=args.codex_timeout,
            keep_stderr=args.codex_keep_stderr,
        ) as codex_client:
            if not args.skip_vision:
                analyses = analyze_frames(
                    frames,
                    client=codex_client,
                    output_path=vision_dir / "frame_analysis.json",
                    model=vision_model,
                    effort=vision_effort,
                )

            if not args.skip_minutes:
                print("Generating minutes with Codex app-server...", flush=True)
                minutes_text = generate_minutes(
                    client=codex_client,
                    video_name=video_path.name,
                    transcript_segments=segments,
                    frame_analyses=analyses,
                    model=minutes_model,
                    effort=minutes_effort,
                )
                minutes_path = run_dir / "minutes.md"
                minutes_path.write_text(minutes_text + "\n", encoding="utf-8")
            else:
                minutes_path = write_basic_minutes(
                    run_dir,
                    video_path.name,
                    transcript_text_path,
                    analyses,
                )

    write_manifest(
        run_dir,
        {
            "video": str(video_path),
            "duration": duration,
            "audio": str(audio_path),
            "frames": len(frames),
            "transcript_text": str(transcript_text_path),
            "transcript_json": str(transcript_json_path),
            "minutes": str(minutes_path),
            "language_code": language_code,
            "scribe_model": scribe_model,
            "diarize": args.diarize,
            "codex_command": args.codex_command,
            "codex_model": codex_model,
            "codex_effort": codex_effort,
            "vision_model": None if args.skip_vision else vision_model,
            "vision_effort": None if args.skip_vision else vision_effort,
            "minutes_model": None if args.skip_minutes else minutes_model,
            "minutes_effort": None if args.skip_minutes else minutes_effort,
            "vision_backend": None if args.skip_vision else "codex-app-server",
            "minutes_backend": None if args.skip_minutes else "codex-app-server",
            "keyterms": keyterms,
        },
    )
    print(f"Saved minutes: {minutes_path}", flush=True)
    return 0
