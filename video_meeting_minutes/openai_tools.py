from __future__ import annotations

import base64
import json
from pathlib import Path

from openai import OpenAI

from .models import FrameAnalysis, FrameEvent, TranscriptSegment
from .timefmt import format_time


def response_text(response: object) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return str(text).strip()
    data = response.model_dump() if hasattr(response, "model_dump") else {}
    fragments: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                fragments.append(str(content["text"]))
    return "\n".join(fragments).strip()


def image_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def analyze_frame(
    client: OpenAI,
    frame: FrameEvent,
    *,
    model: str,
) -> FrameAnalysis:
    prompt = f"""
この画像は会議動画から画面差分で抽出されたフレームです。
時刻: {format_time(frame.timestamp)}

表示内容を日本語で短く解析してください。
- 画面種別
- 読める主要テキスト
- 会議上の論点として関係しそうなこと
- 不明な場合は推測しすぎず「不明」と書く
""".strip()
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_data_url(frame.path)},
                ],
            }
        ],
    )
    return FrameAnalysis(
        index=frame.index,
        timestamp=frame.timestamp,
        image_path=frame.path,
        analysis=response_text(response),
    )


def analyze_frames(
    frames: list[FrameEvent],
    *,
    api_key: str,
    model: str,
    output_path: Path,
) -> list[FrameAnalysis]:
    client = OpenAI(api_key=api_key)
    analyses: list[FrameAnalysis] = []
    for frame in frames:
        print(f"Analyzing frame {frame.index}/{len(frames)} at {format_time(frame.timestamp)}", flush=True)
        analyses.append(analyze_frame(client, frame, model=model))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([analysis.to_dict() for analysis in analyses], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return analyses


def transcript_for_prompt(segments: list[TranscriptSegment]) -> str:
    lines = []
    for segment in segments:
        speaker = f" {segment.speaker}" if segment.speaker else ""
        lines.append(
            f"[{format_time(segment.start)} - {format_time(segment.end)}{speaker}] {segment.text}"
        )
    return "\n".join(lines)


def visual_context_for_prompt(analyses: list[FrameAnalysis]) -> str:
    lines = []
    for analysis in analyses:
        lines.append(
            f"[{format_time(analysis.timestamp)}] frame {analysis.index}: {analysis.analysis}"
        )
    return "\n\n".join(lines)


def generate_minutes(
    *,
    api_key: str,
    model: str,
    video_name: str,
    transcript_segments: list[TranscriptSegment],
    frame_analyses: list[FrameAnalysis],
) -> str:
    client = OpenAI(api_key=api_key)
    prompt = f"""
あなたは会議録作成担当です。
音声文字起こしと、動画画面の変化点ごとの画像解析を突き合わせて、日本語の議事録を作成してください。

制約:
- 音声で明示された内容と、画面に表示されていた内容を混同しない
- 画像解析は補助情報として扱い、断定しすぎない
- 決定事項、宿題、懸念、次回日程を優先して抽出
- 不明点は不明として残す
- Markdownで出力

動画ファイル:
{video_name}

音声タイムライン:
{transcript_for_prompt(transcript_segments)}

画面タイムライン:
{visual_context_for_prompt(frame_analyses)}
""".strip()
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
    )
    return response_text(response)
