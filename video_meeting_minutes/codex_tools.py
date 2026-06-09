from __future__ import annotations

import json
from pathlib import Path

from .codex_app import CodexAppServerClient
from .models import FrameAnalysis, FrameEvent, TranscriptSegment
from .timefmt import format_time


def analyze_frame(
    client: CodexAppServerClient,
    frame: FrameEvent,
    *,
    model: str | None = None,
    effort: str | None = None,
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
    return FrameAnalysis(
        index=frame.index,
        timestamp=frame.timestamp,
        image_path=frame.path,
        analysis=client.ask(prompt, local_images=[frame.path], model=model, effort=effort),
    )


def analyze_frames(
    frames: list[FrameEvent],
    *,
    client: CodexAppServerClient,
    output_path: Path,
    model: str | None = None,
    effort: str | None = None,
) -> list[FrameAnalysis]:
    analyses: list[FrameAnalysis] = []
    for frame in frames:
        print(f"Analyzing frame {frame.index}/{len(frames)} at {format_time(frame.timestamp)}", flush=True)
        analyses.append(analyze_frame(client, frame, model=model, effort=effort))

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
    client: CodexAppServerClient,
    video_name: str,
    transcript_segments: list[TranscriptSegment],
    frame_analyses: list[FrameAnalysis],
    model: str | None = None,
    effort: str | None = None,
) -> str:
    prompt = f"""
あなたは会議録作成担当です。
音声文字起こしと、動画画面の変化点ごとの画像解析を突き合わせて、日本語の議事録を作成してください。

制約:
- 音声で明示された内容と、画面に表示されていた内容を混同しない
- 画像解析は補助情報として扱い、断定しすぎない
- 話者ラベルがある場合は発言要旨に活用する。ただし名前との対応は明示情報がある場合だけ行う
- 不明点は不明として残す
- Markdownで出力
- 下記テンプレートの見出しだけを使い、余計な大見出しを追加しない

テンプレート:
# 議事録: {video_name}

## 参加者
- 確認できた参加者を列挙する。話者ラベルしか分からない場合は speaker_0 のように記載する。

## 決定事項
- 決定した内容を箇条書きにする。なければ「不明」。

## TODO
- 担当者、内容、期限が分かる場合は含める。担当者や期限が不明なら不明と書く。

## 発言要旨
- 会話の流れに沿って、重要な発言・論点を時系列で要約する。
- 可能なら時刻と話者を付ける。

動画ファイル:
{video_name}

音声タイムライン:
{transcript_for_prompt(transcript_segments)}

画面タイムライン:
{visual_context_for_prompt(frame_analyses)}
""".strip()
    return client.ask(prompt, model=model, effort=effort)
